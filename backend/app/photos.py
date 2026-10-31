import hashlib
import io
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel
from sqlalchemy import select

from app.audit import add_audit_event
from app.config import get_settings
from app.deps import CurrentUser, DbSession
from app.meal_ai import AIProviderError, MealRecognition, PROMPT_VERSION, recognize_meal
from app.models import Meal, MealAnalysis, MealPhoto
from app.records import MealIn, MealOut, _meal_out, _replace_food_items

router = APIRouter(prefix="/api", tags=["meal photos"])

MAX_IMAGE_PIXELS = 40_000_000
MAX_IMAGE_EDGE = 12_000
OUTPUT_EDGE = 1600


class ConsentOut(BaseModel):
    granted: bool
    granted_at: datetime | None


class MealPhotoOut(BaseModel):
    id: uuid.UUID
    content_type: str
    byte_size: int
    width: int
    height: int
    created_at: datetime


class MealAnalysisOut(BaseModel):
    id: uuid.UUID
    photo_id: uuid.UUID
    status: str
    provider: str
    model: str
    prompt_version: str
    result: MealRecognition | None
    error_code: str | None
    confirmed_meal_id: uuid.UUID | None


def _photo_out(photo: MealPhoto) -> MealPhotoOut:
    return MealPhotoOut.model_validate(photo, from_attributes=True)


def _analysis_out(analysis: MealAnalysis) -> MealAnalysisOut:
    result = MealRecognition.model_validate_json(analysis.result_json) if analysis.result_json else None
    return MealAnalysisOut(
        id=analysis.id,
        photo_id=analysis.photo_id,
        status=analysis.status,
        provider=analysis.provider,
        model=analysis.model,
        prompt_version=analysis.prompt_version,
        result=result,
        error_code=analysis.error_code,
        confirmed_meal_id=analysis.confirmed_meal_id,
    )


def _owned_photo(db: DbSession, user: CurrentUser, photo_id: uuid.UUID) -> MealPhoto | None:
    return db.scalar(
        select(MealPhoto).where(MealPhoto.id == photo_id, MealPhoto.user_id == user.id)
    )


def _photo_path(storage_key: str) -> Path:
    return get_settings().photo_dir / storage_key


def _normalize_image(raw: bytes) -> tuple[bytes, int, int]:
    try:
        with Image.open(io.BytesIO(raw)) as source:
            source.load()
            if source.format not in {"JPEG", "PNG", "WEBP"}:
                raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "仅支持 JPEG、PNG 或 WebP")
            width, height = source.size
            if width <= 0 or height <= 0 or width > MAX_IMAGE_EDGE or height > MAX_IMAGE_EDGE:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "图片尺寸不符合要求")
            if width * height > MAX_IMAGE_PIXELS:
                raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "图片像素过多")
            image = source.convert("RGB")
            image.thumbnail((OUTPUT_EDGE, OUTPUT_EDGE), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            # 重新编码会移除 EXIF、GPS 和其他原始元数据。
            image.save(output, format="JPEG", quality=82, optimize=True)
            return output.getvalue(), image.width, image.height
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "图片文件无效或已损坏") from exc


@router.get("/ai-consent")
def get_ai_consent(user: CurrentUser) -> ConsentOut:
    return ConsentOut(granted=user.ai_consent_at is not None, granted_at=user.ai_consent_at)


@router.put("/ai-consent")
def grant_ai_consent(request: Request, user: CurrentUser, db: DbSession) -> ConsentOut:
    if user.ai_consent_at is None:
        user.ai_consent_at = datetime.now(timezone.utc)
        add_audit_event(
            db,
            user_id=user.id,
            event_type="ai_consent_granted",
            outcome="success",
            ip_address=request.client.host if request.client else None,
        )
        db.commit()
        db.refresh(user)
    return ConsentOut(granted=True, granted_at=user.ai_consent_at)


@router.delete("/ai-consent")
def revoke_ai_consent(request: Request, user: CurrentUser, db: DbSession) -> ConsentOut:
    if user.ai_consent_at is not None:
        user.ai_consent_at = None
        add_audit_event(
            db,
            user_id=user.id,
            event_type="ai_consent_revoked",
            outcome="success",
            ip_address=request.client.host if request.client else None,
        )
        db.commit()
    return ConsentOut(granted=False, granted_at=None)


@router.post("/meal-photos", status_code=status.HTTP_201_CREATED)
async def upload_meal_photo(request: Request, user: CurrentUser, db: DbSession) -> MealPhotoOut:
    settings = get_settings()
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > settings.max_photo_bytes:
                raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "图片不能超过 10 MB")
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Content-Length 无效") from exc
    raw = await request.body()
    if not raw:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "请选择一张图片")
    if len(raw) > settings.max_photo_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "图片不能超过 10 MB")

    normalized, width, height = _normalize_image(raw)
    digest = hashlib.sha256(raw).hexdigest()
    existing = db.scalar(
        select(MealPhoto).where(MealPhoto.user_id == user.id, MealPhoto.sha256 == digest)
    )
    if existing:
        return _photo_out(existing)

    photo_id = uuid.uuid4()
    storage_key = f"{user.id}/{photo_id}.jpg"
    target = settings.photo_dir / storage_key
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_bytes(normalized)
    temporary.replace(target)

    photo = MealPhoto(
        id=photo_id,
        user_id=user.id,
        storage_key=storage_key,
        sha256=digest,
        content_type="image/jpeg",
        byte_size=len(normalized),
        width=width,
        height=height,
    )
    db.add(photo)
    try:
        db.commit()
    except Exception:
        target.unlink(missing_ok=True)
        raise
    db.refresh(photo)
    return _photo_out(photo)


@router.get("/meal-photos/{photo_id}", response_class=FileResponse)
def get_meal_photo(photo_id: uuid.UUID, user: CurrentUser, db: DbSession) -> FileResponse:
    photo = _owned_photo(db, user, photo_id)
    if photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "照片不存在")
    path = _photo_path(photo.storage_key)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "照片文件不存在")
    return FileResponse(
        path,
        media_type=photo.content_type,
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/meal-photos/{photo_id}/analyze")
def analyze_meal_photo(
    photo_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> MealAnalysisOut:
    if user.ai_consent_at is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "请先同意将本次照片发送给 AI 服务商处理")
    photo = _owned_photo(db, user, photo_id)
    if photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "照片不存在")

    settings = get_settings()
    if not settings.deepseek_api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI 尚未配置，可继续手工记录")
    analysis = db.scalar(
        select(MealAnalysis).where(
            MealAnalysis.photo_id == photo.id, MealAnalysis.user_id == user.id
        )
    )
    if analysis and analysis.status in {"succeeded", "confirmed"}:
        return _analysis_out(analysis)
    if analysis is None:
        analysis = MealAnalysis(
            user_id=user.id,
            photo_id=photo.id,
            status="processing",
            provider="deepseek",
            model=settings.deepseek_model,
            prompt_version=PROMPT_VERSION,
        )
        db.add(analysis)
    else:
        analysis.status = "processing"
        analysis.error_code = None
    db.commit()
    db.refresh(analysis)

    try:
        result = recognize_meal(_photo_path(photo.storage_key).read_bytes(), settings)
    except AIProviderError as exc:
        analysis.status = "failed"
        analysis.error_code = exc.code
        db.commit()
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "AI 识别暂时失败，可稍后重试或手工记录"
        ) from exc

    analysis.status = "succeeded"
    analysis.result_json = result.model_dump_json()
    analysis.error_code = None
    db.commit()
    db.refresh(analysis)
    return _analysis_out(analysis)


@router.get("/meal-photos/{photo_id}/analysis")
def get_meal_analysis(
    photo_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> MealAnalysisOut:
    analysis = db.scalar(
        select(MealAnalysis).where(
            MealAnalysis.photo_id == photo_id, MealAnalysis.user_id == user.id
        )
    )
    if analysis is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "识别结果不存在")
    return _analysis_out(analysis)


@router.post("/meal-photos/{photo_id}/confirm", status_code=status.HTTP_201_CREATED)
def confirm_meal_analysis(
    photo_id: uuid.UUID,
    body: MealIn,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> MealOut:
    analysis = db.scalar(
        select(MealAnalysis).where(
            MealAnalysis.photo_id == photo_id, MealAnalysis.user_id == user.id
        )
    )
    if analysis is None or analysis.status not in {"succeeded", "confirmed"}:
        raise HTTPException(status.HTTP_409_CONFLICT, "没有可确认的识别草稿")
    if analysis.confirmed_meal_id:
        meal = db.scalar(
            select(Meal).where(
                Meal.id == analysis.confirmed_meal_id, Meal.user_id == user.id
            )
        )
        if meal:
            return _meal_out(db, meal)

    meal = Meal(
        user_id=user.id,
        photo_id=photo_id,
        eaten_at=body.eaten_at,
        meal_type=body.meal_type,
        status="confirmed",
        notes=body.notes,
    )
    db.add(meal)
    db.flush()
    _replace_food_items(db, meal, user.id, body.food_items)
    analysis.status = "confirmed"
    analysis.confirmed_meal_id = meal.id
    add_audit_event(
        db,
        user_id=user.id,
        event_type="meal_ai_confirmed",
        outcome="success",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    db.refresh(meal)
    return _meal_out(db, meal)

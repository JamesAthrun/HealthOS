import hashlib
import io
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Body, HTTPException, Request, status
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.audit import add_audit_event, commit_with_tenant_context, set_tenant_context
from app.config import get_settings
from app.dashboard import _user_timezone
from app.deps import CurrentUser, DbSession
from app.meal_ai import (
    AIProviderError,
    EstimatedNutrition,
    EstimateItemIn,
    MAX_MEAL_PHOTOS,
    MULTI_PROMPT_VERSION,
    MealRecognition,
    PROMPT_VERSION,
    estimate_nutrition,
    recognize_meal,
    recognize_meal_photos,
    recognize_meal_text,
)
from app.models import Meal, MealAnalysis, MealPhoto
from app.records import MealIn, MealOut, _meal_out, _replace_food_items, set_meal_photos

router = APIRouter(prefix="/api", tags=["meal photos"])
logger = logging.getLogger(__name__)

# iPhone 默认拍 HEIC；Pillow 本身不支持，需要注册 pillow-heif 解码器。
register_heif_opener()

MAX_IMAGE_PIXELS = 40_000_000
MAX_IMAGE_EDGE = 12_000
OUTPUT_EDGE = 1600


class ConsentOut(BaseModel):
    granted: bool
    granted_at: datetime | None


class AnalyzeIn(BaseModel):
    # 识别不准时用户补充的说明，例如“这是牛肉面，只吃了一半”
    hint: str | None = Field(default=None, max_length=200)


class MealTextIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 文字或语音输入法转出来的一句话，例如“中午吃了一碗牛肉面加个卤蛋”
    text: str = Field(min_length=1, max_length=300)


class EstimateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[EstimateItemIn] = Field(min_length=1, max_length=20)


class EstimateOut(BaseModel):
    items: list[EstimatedNutrition]


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
            # iPhone 的 JPEG 常带 HDR 增益图/深度图，Pillow 识别为 MPO（多图 JPEG），只取主图
            if source.format not in {"JPEG", "MPO", "PNG", "WEBP", "HEIF"}:
                logger.warning("photo format not allowed: %s", source.format)
                raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "仅支持 JPEG、PNG、WebP 或 HEIC")
            width, height = source.size
            if width <= 0 or height <= 0 or width > MAX_IMAGE_EDGE or height > MAX_IMAGE_EDGE:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "图片尺寸不符合要求")
            if width * height > MAX_IMAGE_PIXELS:
                raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "图片像素过多")
            # 手机照片靠 EXIF 标记方向，去掉元数据前先把像素转正
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((OUTPUT_EDGE, OUTPUT_EDGE), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            # 重新编码会移除 EXIF、GPS 和其他原始元数据。
            image.save(output, format="JPEG", quality=82, optimize=True)
            return output.getvalue(), image.width, image.height
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "图片文件无效或已损坏") from exc


def _normalize_photo_upload(raw: bytes, request: Request) -> tuple[bytes, int, int]:
    try:
        return _normalize_image(raw)
    except HTTPException as exc:
        # 只记录格式特征（文件头前 16 字节），不记录图片内容
        logger.warning(
            "photo rejected: status=%s detail=%s content_type=%s bytes=%d head=%s cause=%r",
            exc.status_code,
            exc.detail,
            request.headers.get("content-type"),
            len(raw),
            raw[:16].hex(),
            exc.__cause__,
        )
        raise


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

    normalized, width, height = _normalize_photo_upload(raw, request)
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
    set_tenant_context(db, user.id)
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
    photo_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
    body: Annotated[AnalyzeIn | None, Body()] = None,
) -> MealAnalysisOut:
    if user.ai_consent_at is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "请先同意将本次照片发送给 AI 服务商处理")
    photo = _owned_photo(db, user, photo_id)
    if photo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "照片不存在")
    hint = body.hint.strip() if body and body.hint and body.hint.strip() else None

    settings = get_settings()
    if not settings.deepseek_api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI 尚未配置，可继续手工记录")
    analysis = db.scalar(
        select(MealAnalysis).where(
            MealAnalysis.photo_id == photo.id, MealAnalysis.user_id == user.id
        )
    )
    if analysis and analysis.status == "confirmed":
        if hint:
            raise HTTPException(status.HTTP_409_CONFLICT, "这张照片已确认记录，不能再重新识别")
        return _analysis_out(analysis)
    # 没有更正说明时复用已有结果，避免重复调用 AI
    if analysis and analysis.status == "succeeded" and not hint:
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
        analysis.model = settings.deepseek_model
        analysis.prompt_version = PROMPT_VERSION
    commit_with_tenant_context(db, user.id)
    db.refresh(analysis)

    try:
        result = recognize_meal(_photo_path(photo.storage_key).read_bytes(), settings, hint=hint)
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
    commit_with_tenant_context(db, user.id)
    db.refresh(analysis)
    return _analysis_out(analysis)


class MultiPhotoAnalyzeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    photo_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_MEAL_PHOTOS)
    # 识别前写的说明，例如“两个人分着吃”“还喝了一杯奶茶”
    note: str | None = Field(default=None, max_length=300)
    # 识别后觉得不准时补充的更正
    hint: str | None = Field(default=None, max_length=200)


@router.post("/meal-recognitions")
def analyze_meal_photos(body: MultiPhotoAnalyzeIn, user: CurrentUser, db: DbSession) -> MealAnalysisOut:
    """同一餐的多张照片 + 说明一起识别。结果记在第一张照片上，之后照常用 /meal-photos/{第一张}/confirm 确认。"""
    if user.ai_consent_at is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "请先同意将饮食照片或文字发送给 AI 服务商处理")
    photo_ids = list(dict.fromkeys(body.photo_ids))
    photos = []
    for photo_id in photo_ids:
        photo = _owned_photo(db, user, photo_id)
        if photo is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "照片不存在")
        photos.append(photo)
    settings = get_settings()
    if not settings.deepseek_api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI 尚未配置，可继续手工记录")
    note = body.note.strip() if body.note and body.note.strip() else None
    hint = body.hint.strip() if body.hint and body.hint.strip() else None

    primary = photos[0]
    analysis = db.scalar(
        select(MealAnalysis).where(MealAnalysis.photo_id == primary.id, MealAnalysis.user_id == user.id)
    )
    if analysis and analysis.status == "confirmed":
        raise HTTPException(status.HTTP_409_CONFLICT, "这张照片已确认记录，不能再重新识别")
    if analysis is None:
        analysis = MealAnalysis(user_id=user.id, photo_id=primary.id, provider="deepseek")
        db.add(analysis)
    analysis.status = "processing"
    analysis.error_code = None
    analysis.model = settings.deepseek_model
    analysis.prompt_version = MULTI_PROMPT_VERSION
    commit_with_tenant_context(db, user.id)
    db.refresh(analysis)

    try:
        images = [_photo_path(photo.storage_key).read_bytes() for photo in photos]
        result = recognize_meal_photos(images, settings, note=note, hint=hint)
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
    commit_with_tenant_context(db, user.id)
    db.refresh(analysis)
    return _analysis_out(analysis)


class PhotoPreviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    photo_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_MEAL_PHOTOS)
    note: str | None = Field(default=None, max_length=300)


@router.post("/meal-recognitions/preview")
def preview_meal_photos(body: PhotoPreviewIn, user: CurrentUser, db: DbSession) -> MealRecognition:
    """编辑已有的一餐时用照片重新识别：只返回草稿，不保存；用户确认后走 PATCH /api/meals/{id}。"""
    if user.ai_consent_at is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "请先同意将饮食照片或文字发送给 AI 服务商处理")
    photos = []
    for photo_id in dict.fromkeys(body.photo_ids):
        photo = _owned_photo(db, user, photo_id)
        if photo is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "照片不存在")
        photos.append(photo)
    settings = get_settings()
    if not settings.deepseek_api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI 尚未配置，可继续手工记录")
    note = body.note.strip() if body.note and body.note.strip() else None
    try:
        images = [_photo_path(photo.storage_key).read_bytes() for photo in photos]
        return recognize_meal_photos(images, settings, note=note)
    except FileNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "照片文件不存在") from exc
    except AIProviderError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "AI 识别暂时失败，可稍后重试或手工修改"
        ) from exc


@router.post("/meal-text/analyze")
def analyze_meal_text(body: MealTextIn, user: CurrentUser) -> MealRecognition:
    """文字/语音描述 → 饮食草稿。不保存任何内容；用户确认后走 POST /api/meals。"""
    if user.ai_consent_at is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "请先同意将饮食照片或文字发送给 AI 服务商处理")
    text = body.text.strip()
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "请描述吃了什么")
    settings = get_settings()
    if not settings.deepseek_api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI 尚未配置，可继续手工记录")
    now_local = datetime.now(_user_timezone(user)).strftime("%Y-%m-%d %H:%M")
    try:
        return recognize_meal_text(text, settings, now_local)
    except AIProviderError as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "AI 识别暂时失败，可稍后重试或手工记录"
        ) from exc


@router.post("/meal-text/estimate")
def estimate_meal_nutrition(body: EstimateIn, user: CurrentUser) -> EstimateOut:
    """按用户填写的食物清单估算热量和营养素；不保存，结果与输入一一对应。"""
    if user.ai_consent_at is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "请先在“我的 → 账号设置”或拍照/文字记录中同意 AI 饮食识别")
    settings = get_settings()
    if not settings.deepseek_api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI 尚未配置，可以手动填写热量")
    try:
        return EstimateOut(items=estimate_nutrition(body.items, settings))
    except AIProviderError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "营养估算暂时失败，可稍后重试") from exc


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
    set_meal_photos(db, meal, user.id, [photo_id, *body.photo_ids])
    analysis.status = "confirmed"
    analysis.confirmed_meal_id = meal.id
    add_audit_event(
        db,
        user_id=user.id,
        event_type="meal_ai_confirmed",
        outcome="success",
        ip_address=request.client.host if request.client else None,
    )
    commit_with_tenant_context(db, user.id)
    db.refresh(meal)
    return _meal_out(db, meal)

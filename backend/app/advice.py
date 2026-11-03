import json
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, select

from app.advice_service import (
    PROMPT_VERSION,
    AdviceContent,
    build_advice_context,
    run_advice_job,
)
from app.audit import add_audit_event, commit_with_tenant_context, set_tenant_context
from app.config import get_settings
from app.dashboard import _user_timezone
from app.deps import CurrentUser, DbSession
from app.models import Advice, UserNote

router = APIRouter(prefix="/api", tags=["advice"])

NoteCategory = Literal["limitation", "preference", "tried", "temporary"]


def _future_aware_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("过期时间必须包含时区")
    if value <= datetime.now(timezone.utc):
        raise ValueError("过期时间必须晚于当前时间")
    return value


class ConsentOut(BaseModel):
    granted: bool
    granted_at: datetime | None


class NoteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=100)
    category: NoteCategory
    expires_at: datetime | None = None

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("内容不能为空")
        return value.strip()

    @field_validator("expires_at")
    @classmethod
    def validate_expires_at(cls, value: datetime | None) -> datetime | None:
        return _future_aware_datetime(value)

    @model_validator(mode="after")
    def validate_expiry(self) -> "NoteIn":
        if self.category != "temporary" and self.expires_at is not None:
            raise ValueError("只有临时记录可以设置过期时间")
        return self


class NotePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str | None = Field(default=None, min_length=1, max_length=100)
    category: NoteCategory | None = None
    expires_at: datetime | None = None

    @field_validator("content")
    @classmethod
    def strip_content(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("内容不能为空")
        return value.strip() if value is not None else None

    @field_validator("expires_at")
    @classmethod
    def validate_expires_at(cls, value: datetime | None) -> datetime | None:
        return _future_aware_datetime(value)

    @model_validator(mode="after")
    def validate_category_expiry(self) -> "NotePatch":
        if self.category not in {None, "temporary"} and self.expires_at is not None:
            raise ValueError("只有临时记录可以设置过期时间")
        return self


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    content: str
    category: NoteCategory
    expires_at: datetime | None
    created_at: datetime
    updated_at: datetime


class GenerateAdviceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    for_date: date | None = None


class AdviceOut(BaseModel):
    id: uuid.UUID
    kind: Literal["daily", "weekly"]
    for_date: date
    status: Literal["pending", "succeeded", "failed"]
    content: AdviceContent | None
    observations: list[str]
    feedback: str | None
    feedback_reason: str | None
    error_code: str | None
    created_at: datetime
    updated_at: datetime


class FeedbackIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feedback: Literal["useful", "not_applicable", "unsafe"]
    reason: str | None = Field(
        default=None,
        max_length=500,
        description="反馈原因；当 remember=true 时必填且最多 100 个字符。",
    )
    remember: bool = Field(
        default=False,
        description="仅适用于 not_applicable；保存为‘关于我’记忆，重复提交会更新同一条。",
    )

    @field_validator("reason")
    @classmethod
    def strip_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @model_validator(mode="after")
    def validate_memory(self) -> "FeedbackIn":
        if not self.remember:
            return self
        if self.feedback != "not_applicable":
            raise ValueError("只有不适用的反馈可以记住")
        if not self.reason:
            raise ValueError("记住反馈时请填写原因")
        if len(self.reason) > 100:
            raise ValueError("记住的原因不能超过 100 个字符")
        return self


def _note_out(note: UserNote) -> NoteOut:
    return NoteOut.model_validate(note)


def _advice_out(advice: Advice, user: CurrentUser) -> AdviceOut:
    tz = _user_timezone(user)
    content = AdviceContent.model_validate_json(advice.content_json) if advice.content_json else None
    return AdviceOut(
        id=advice.id,
        kind=advice.kind,  # type: ignore[arg-type]
        for_date=advice.for_date.astimezone(tz).date(),
        status=advice.status,  # type: ignore[arg-type]
        content=content,
        observations=json.loads(advice.observation_ids_json),
        feedback=advice.feedback,
        feedback_reason=advice.feedback_reason,
        error_code=advice.error_code,
        created_at=advice.created_at,
        updated_at=advice.updated_at,
    )


def _owned_advice(db: DbSession, user: CurrentUser, advice_id: uuid.UUID) -> Advice:
    advice = db.scalar(
        select(Advice).where(Advice.id == advice_id, Advice.user_id == user.id)
    )
    if advice is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "建议不存在")
    return advice


def _mark_stale_advice_failed(db: DbSession, user: CurrentUser) -> None:
    timeout_seconds = max(120, round(get_settings().deepseek_timeout_seconds * 2 + 30))
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
    stale = list(
        db.scalars(
            select(Advice).where(
                Advice.user_id == user.id,
                Advice.status == "pending",
                Advice.created_at < cutoff,
            )
        )
    )
    if not stale:
        return
    for item in stale:
        item.status = "failed"
        item.error_code = "AI_JOB_INTERRUPTED"
    commit_with_tenant_context(db, user.id)


@router.get("/planning-consent")
def get_planning_consent(user: CurrentUser) -> ConsentOut:
    return ConsentOut(granted=user.planning_consent_at is not None, granted_at=user.planning_consent_at)


@router.put("/planning-consent")
def grant_planning_consent(request: Request, user: CurrentUser, db: DbSession) -> ConsentOut:
    if user.planning_consent_at is None:
        user.planning_consent_at = datetime.now(timezone.utc)
        add_audit_event(
            db,
            user_id=user.id,
            event_type="planning_consent_granted",
            outcome="success",
            ip_address=request.client.host if request.client else None,
        )
        db.commit()
        db.refresh(user)
    return ConsentOut(granted=True, granted_at=user.planning_consent_at)


@router.delete("/planning-consent")
def revoke_planning_consent(request: Request, user: CurrentUser, db: DbSession) -> ConsentOut:
    if user.planning_consent_at is not None:
        user.planning_consent_at = None
        add_audit_event(
            db,
            user_id=user.id,
            event_type="planning_consent_revoked",
            outcome="success",
            ip_address=request.client.host if request.client else None,
        )
        db.commit()
    return ConsentOut(granted=False, granted_at=None)


@router.get("/notes")
def list_notes(user: CurrentUser, db: DbSession) -> list[NoteOut]:
    notes = db.scalars(
        select(UserNote)
        .where(UserNote.user_id == user.id)
        .order_by(UserNote.created_at.desc())
    )
    return [_note_out(note) for note in notes]


@router.post("/notes", status_code=status.HTTP_201_CREATED)
def create_note(body: NoteIn, user: CurrentUser, db: DbSession) -> NoteOut:
    expires_at = body.expires_at
    if body.category == "temporary" and expires_at is None:
        expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    note = UserNote(
        user_id=user.id,
        content=body.content,
        category=body.category,
        expires_at=expires_at,
    )
    db.add(note)
    commit_with_tenant_context(db, user.id)
    db.refresh(note)
    return _note_out(note)


@router.patch("/notes/{note_id}")
def patch_note(note_id: uuid.UUID, body: NotePatch, user: CurrentUser, db: DbSession) -> NoteOut:
    note = db.scalar(
        select(UserNote).where(UserNote.id == note_id, UserNote.user_id == user.id)
    )
    if note is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "记录不存在")
    update = body.model_dump(exclude_unset=True)
    for field, value in update.items():
        setattr(note, field, value.strip() if field == "content" and value else value)
    if note.category == "temporary" and note.expires_at is None:
        note.expires_at = datetime.now(timezone.utc) + timedelta(days=7)
    if note.category != "temporary":
        note.expires_at = None
    commit_with_tenant_context(db, user.id)
    db.refresh(note)
    return _note_out(note)


@router.delete("/notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(note_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    note = db.scalar(
        select(UserNote).where(UserNote.id == note_id, UserNote.user_id == user.id)
    )
    if note is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "记录不存在")
    db.delete(note)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _create_advice(
    kind: Literal["daily", "weekly"],
    body: GenerateAdviceIn,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    db: DbSession,
) -> AdviceOut:
    if user.planning_consent_at is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "请先同意使用健康摘要生成规划")
    if not get_settings().deepseek_api_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI 服务尚未配置")
    _mark_stale_advice_failed(db, user)
    since = datetime.now(timezone.utc) - timedelta(days=1)
    recent_count = db.scalar(
        select(func.count(Advice.id)).where(
            Advice.user_id == user.id,
            Advice.kind == kind,
            Advice.created_at >= since,
        )
    )
    if recent_count is not None and recent_count >= 5:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "每类规划每天最多生成 5 次")

    tz = _user_timezone(user)
    today = datetime.now(tz).date()
    if body.for_date is not None:
        selected = body.for_date
    elif kind == "daily":
        selected = today + timedelta(days=1)
    else:
        selected = today + timedelta(days=(7 - today.weekday()) % 7 or 7)
    context, observations = build_advice_context(db, user, kind=kind, for_date=selected)
    advice = Advice(
        user_id=user.id,
        kind=kind,
        for_date=datetime.combine(selected, time.min, tzinfo=tz).astimezone(timezone.utc),
        status="pending",
        context_json=json.dumps(context, ensure_ascii=False, separators=(",", ":")),
        content_json=None,
        observation_ids_json=json.dumps([item.id for item in observations]),
        provider="deepseek",
        model=get_settings().deepseek_model,
        prompt_version=PROMPT_VERSION,
    )
    db.add(advice)
    commit_with_tenant_context(db, user.id)
    db.refresh(advice)
    background_tasks.add_task(run_advice_job, advice.id, user.id)
    return _advice_out(advice, user)


@router.post("/advice/daily", status_code=status.HTTP_202_ACCEPTED)
def create_daily_advice(
    body: GenerateAdviceIn,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    db: DbSession,
) -> AdviceOut:
    return _create_advice("daily", body, background_tasks, user, db)


@router.post("/advice/weekly", status_code=status.HTTP_202_ACCEPTED)
def create_weekly_advice(
    body: GenerateAdviceIn,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    db: DbSession,
) -> AdviceOut:
    return _create_advice("weekly", body, background_tasks, user, db)


@router.get("/advice")
def list_advice(user: CurrentUser, db: DbSession) -> list[AdviceOut]:
    _mark_stale_advice_failed(db, user)
    rows = db.scalars(
        select(Advice)
        .where(Advice.user_id == user.id)
        .order_by(Advice.created_at.desc())
        .limit(30)
    )
    return [_advice_out(item, user) for item in rows]


@router.get("/advice/{advice_id}")
def get_advice(advice_id: uuid.UUID, user: CurrentUser, db: DbSession) -> AdviceOut:
    _mark_stale_advice_failed(db, user)
    return _advice_out(_owned_advice(db, user, advice_id), user)


@router.post("/advice/{advice_id}/feedback")
def give_feedback(
    advice_id: uuid.UUID, body: FeedbackIn, user: CurrentUser, db: DbSession
) -> AdviceOut:
    advice = _owned_advice(db, user, advice_id)
    if advice.status != "succeeded":
        raise HTTPException(status.HTTP_409_CONFLICT, "只能评价已经生成的建议")
    advice.feedback = body.feedback
    advice.feedback_reason = body.reason
    remembered_note = db.scalar(
        select(UserNote).where(
            UserNote.user_id == user.id,
            UserNote.source_advice_id == advice.id,
        )
    )
    if body.remember:
        if remembered_note is None:
            db.add(
                UserNote(
                    user_id=user.id,
                    content=body.reason,
                    category="tried",
                    source_advice_id=advice.id,
                )
            )
        else:
            remembered_note.content = body.reason
            remembered_note.category = "tried"
            remembered_note.expires_at = None
    elif remembered_note is not None:
        db.delete(remembered_note)
    commit_with_tenant_context(db, user.id)
    db.refresh(advice)
    return _advice_out(advice, user)

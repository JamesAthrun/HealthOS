import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import add_audit_event, commit_with_tenant_context
from app.dashboard import _user_timezone
from app.deps import CurrentUser, DbSession
from app.models import Profile, User, WeightLog

router = APIRouter(prefix="/api", tags=["weights"])

# 与上一条记录相比，平均每天变化超过这个值就提示用户确认是否输错
SUSPICIOUS_DAILY_CHANGE_KG = 2.0
TREND_DAYS = 30


class WeightIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    measured_on: date
    weight_kg: float = Field(ge=20, le=500)
    waist_cm: float | None = Field(default=None, ge=30, le=250)
    body_fat_pct: float | None = Field(default=None, ge=2, le=75)
    notes: str | None = Field(default=None, max_length=500)


class WeightPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    measured_on: date | None = None
    weight_kg: float | None = Field(default=None, ge=20, le=500)
    waist_cm: float | None = Field(default=None, ge=30, le=250)
    body_fat_pct: float | None = Field(default=None, ge=2, le=75)
    notes: str | None = Field(default=None, max_length=500)


class WeightOut(WeightIn):
    id: uuid.UUID
    warning: str | None = None


class WeightPoint(BaseModel):
    date: date
    weight_kg: float


class TrendPoint(WeightPoint):
    avg_7d_kg: float


class WeightSummary(BaseModel):
    initial: WeightPoint | None
    current: WeightPoint | None
    target_weight_kg: float | None
    change_kg: float | None = Field(description="当前 − 初始")
    to_target_kg: float | None = Field(description="当前 − 目标；正数表示高于目标")
    change_7d_kg: float | None
    change_30d_kg: float | None
    bmi: float | None
    trend: list[TrendPoint]
    notice: str = "仅供健康习惯参考，不是医疗建议"


@dataclass(frozen=True)
class WeightStats:
    initial: WeightPoint | None
    current: WeightPoint | None
    change_7d_kg: float | None
    change_30d_kg: float | None


def _round(value: float) -> float:
    return round(value, 1)


def change_over(points: list[WeightPoint], today: date, days: int) -> float | None:
    """窗口内最新记录与窗口起点附近记录之差；数据不够时返回 None。

    points 必须按日期升序。基准取窗口起点当天或之前最近的一条（最多再往前一个窗口），
    没有的话取窗口内最早的一条。
    """
    if len(points) < 2:
        return None
    latest = points[-1]
    start = today - timedelta(days=days)
    if latest.date <= start:
        return None
    before = [p for p in points if start - timedelta(days=days) <= p.date <= start]
    baseline = before[-1] if before else next(p for p in points if p.date > start)
    if baseline.date == latest.date:
        return None
    return _round(latest.weight_kg - baseline.weight_kg)


def trend_points(points: list[WeightPoint], today: date, days: int = TREND_DAYS) -> list[TrendPoint]:
    """最近 days 天的记录，并附 7 天移动平均（窗口内已有记录的平均）。"""
    start = today - timedelta(days=days - 1)
    result = []
    for point in points:
        if point.date < start:
            continue
        window = [p.weight_kg for p in points if point.date - timedelta(days=6) <= p.date <= point.date]
        result.append(
            TrendPoint(date=point.date, weight_kg=point.weight_kg, avg_7d_kg=_round(sum(window) / len(window)))
        )
    return result


def _points(db: Session, user_id: uuid.UUID) -> list[WeightPoint]:
    rows = db.execute(
        select(WeightLog.measured_on, WeightLog.weight_kg)
        .where(WeightLog.user_id == user_id)
        .order_by(WeightLog.measured_on)
    )
    return [WeightPoint(date=day, weight_kg=weight) for day, weight in rows]


def weight_stats(db: Session, user: User, today: date) -> WeightStats:
    points = _points(db, user.id)
    return WeightStats(
        initial=points[0] if points else None,
        current=points[-1] if points else None,
        change_7d_kg=change_over(points, today, 7),
        change_30d_kg=change_over(points, today, 30),
    )


def _today(user: User) -> date:
    return datetime.now(_user_timezone(user)).date()


def _check_not_future(user: User, day: date) -> None:
    if day > _today(user):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "日期不能晚于今天")


def sync_profile_weight(db: Session, user_id: uuid.UUID) -> None:
    """profiles.weight_kg 始终等于最新一条体重记录；没有记录时清空。"""
    db.flush()
    latest = db.scalar(
        select(WeightLog.weight_kg)
        .where(WeightLog.user_id == user_id)
        .order_by(WeightLog.measured_on.desc())
        .limit(1)
    )
    profile = db.scalar(select(Profile).where(Profile.user_id == user_id))
    if profile is None:
        if latest is None:
            return
        profile = Profile(user_id=user_id)
        db.add(profile)
    profile.weight_kg = latest


def upsert_weight(db: Session, user_id: uuid.UUID, day: date, weight_kg: float) -> tuple[WeightLog, bool]:
    """同一天只保留一条记录；返回 (记录, 是否新建)。"""
    log = db.scalar(
        select(WeightLog).where(WeightLog.user_id == user_id, WeightLog.measured_on == day)
    )
    created = log is None
    if log is None:
        log = WeightLog(user_id=user_id, measured_on=day, weight_kg=weight_kg)
        db.add(log)
    else:
        log.weight_kg = weight_kg
    return log, created


def _suspicious_change_warning(db: Session, log: WeightLog) -> str | None:
    previous = db.scalar(
        select(WeightLog)
        .where(WeightLog.user_id == log.user_id, WeightLog.measured_on < log.measured_on)
        .order_by(WeightLog.measured_on.desc())
        .limit(1)
    )
    if previous is None:
        return None
    days = (log.measured_on - previous.measured_on).days
    if abs(log.weight_kg - previous.weight_kg) / days > SUSPICIOUS_DAILY_CHANGE_KG:
        return f"与 {previous.measured_on.isoformat()} 的 {previous.weight_kg} kg 相比变化较大，请确认是否输错"
    return None


def _weight_out(db: Session, log: WeightLog, *, check: bool = False) -> WeightOut:
    out = WeightOut.model_validate(log, from_attributes=True)
    if check:
        out.warning = _suspicious_change_warning(db, log)
    return out


def _owned(db: Session, user_id: uuid.UUID, weight_id: uuid.UUID) -> WeightLog:
    log = db.scalar(select(WeightLog).where(WeightLog.id == weight_id, WeightLog.user_id == user_id))
    if log is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "记录不存在")
    return log


@router.get("/weights")
def list_weights(
    user: CurrentUser, db: DbSession, limit: int = Query(default=366, ge=1, le=1000)
) -> list[WeightOut]:
    logs = db.scalars(
        select(WeightLog)
        .where(WeightLog.user_id == user.id)
        .order_by(WeightLog.measured_on.desc())
        .limit(limit)
    )
    return [_weight_out(db, log) for log in logs]


@router.post("/weights", status_code=status.HTTP_201_CREATED)
def create_or_replace_weight(
    body: WeightIn, response: Response, user: CurrentUser, db: DbSession
) -> WeightOut:
    _check_not_future(user, body.measured_on)
    log, created = upsert_weight(db, user.id, body.measured_on, body.weight_kg)
    log.waist_cm = body.waist_cm
    log.body_fat_pct = body.body_fat_pct
    log.notes = body.notes
    sync_profile_weight(db, user.id)
    commit_with_tenant_context(db, user.id)
    db.refresh(log)
    if not created:
        response.status_code = status.HTTP_200_OK
    return _weight_out(db, log, check=True)


@router.get("/weights/summary")
def weights_summary(user: CurrentUser, db: DbSession) -> WeightSummary:
    today = _today(user)
    points = _points(db, user.id)
    profile = db.scalar(select(Profile).where(Profile.user_id == user.id))
    current = points[-1] if points else None
    target = profile.target_weight_kg if profile else None
    height = profile.height_cm if profile else None
    return WeightSummary(
        initial=points[0] if points else None,
        current=current,
        target_weight_kg=target,
        change_kg=_round(current.weight_kg - points[0].weight_kg) if current else None,
        to_target_kg=_round(current.weight_kg - target) if current and target else None,
        change_7d_kg=change_over(points, today, 7),
        change_30d_kg=change_over(points, today, 30),
        bmi=_round(current.weight_kg / (height / 100) ** 2) if current and height else None,
        trend=trend_points(points, today),
    )


@router.get("/weights/{weight_id}")
def get_weight(weight_id: uuid.UUID, user: CurrentUser, db: DbSession) -> WeightOut:
    return _weight_out(db, _owned(db, user.id, weight_id))


@router.patch("/weights/{weight_id}")
def patch_weight(
    weight_id: uuid.UUID, body: WeightPatch, user: CurrentUser, db: DbSession
) -> WeightOut:
    log = _owned(db, user.id, weight_id)
    fields = body.model_fields_set
    if "measured_on" in fields and body.measured_on is not None and body.measured_on != log.measured_on:
        _check_not_future(user, body.measured_on)
        clash = db.scalar(
            select(WeightLog.id).where(
                WeightLog.user_id == user.id, WeightLog.measured_on == body.measured_on
            )
        )
        if clash is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "这一天已经有体重记录")
        log.measured_on = body.measured_on
    if "weight_kg" in fields:
        if body.weight_kg is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "体重不能为空")
        log.weight_kg = body.weight_kg
    for field in ("waist_cm", "body_fat_pct", "notes"):
        if field in fields:
            setattr(log, field, getattr(body, field))
    sync_profile_weight(db, user.id)
    commit_with_tenant_context(db, user.id)
    db.refresh(log)
    return _weight_out(db, log, check=True)


@router.delete("/weights/{weight_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_weight(weight_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession) -> None:
    log = _owned(db, user.id, weight_id)
    db.delete(log)
    sync_profile_weight(db, user.id)
    add_audit_event(
        db,
        user_id=user.id,
        event_type="record_deleted",
        outcome="success",
        ip_address=request.client.host if request.client else None,
    )
    commit_with_tenant_context(db, user.id)

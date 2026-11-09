"""生理周期：记录与预测。预测是纯函数，不经过 AI；仅供提前准备，不能用于避孕或备孕判断。"""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.audit import add_audit_event, commit_with_tenant_context
from app.deps import CurrentUser, DbSession
from app.models import CyclePeriod, Profile, User
from app.weights import _today

router = APIRouter(prefix="/api", tags=["cycles"])

DEFAULT_CYCLE_DAYS = 28
DEFAULT_PERIOD_DAYS = 5
MAX_PERIOD_DAYS = 15
RECENT_CYCLES = 6
VALID_CYCLE_RANGE = (15, 60)
NOTICE = "预测只是根据历史记录的估算，仅用于提前准备，不能用于避孕或备孕判断"
# 经前（黄体期）静息代谢略升高，热量参考加一点
LUTEAL_KCAL_BONUS = 150
LUTEAL_TIPS = ["经前身体消耗略增，今天的热量参考已加 150 kcal；想吃甜食时可以选水果、酸奶。"]
MENSTRUAL_TIPS = [
    "经期注意补铁：红肉、动物肝脏、血豆腐、深绿叶菜，搭配富含维生素 C 的水果帮助吸收。",
    "浓茶和咖啡会影响铁的吸收，尽量别和正餐一起喝。",
]

Flow = Literal["light", "medium", "heavy"]
Symptom = Literal["cramps", "bloating", "headache", "mood", "breast_tenderness", "fatigue", "acne"]
Phase = Literal["menstrual", "follicular", "ovulation", "luteal", "late"]


# ---------- 预测算法（纯函数） ----------


@dataclass(frozen=True)
class PeriodSpan:
    start: date
    end: date | None


class CycleSummary(BaseModel):
    has_data: bool
    cycle_day: int | None = Field(description="今天是本周期第几天（最近一次开始日为第 1 天）")
    phase: Phase | None
    in_period: bool
    avg_cycle_days: int
    avg_period_days: int
    insufficient_data: bool = Field(description="有效周期少于 2 个，按 28 天估算")
    next_start: date | None
    next_start_earliest: date | None
    next_start_latest: date | None
    days_until_next: int | None
    late_days: int | None
    alerts: list[str]
    kcal_bonus: int = Field(default=0, description="今天的热量参考要加多少（经前 +150，关闭自动调整时为 0）")
    tips: list[str] = Field(default_factory=list, description="和当前阶段相关的饮食提示")
    notice: str = NOTICE


def _valid_cycle_lengths(spans: list[PeriodSpan]) -> list[int]:
    starts = [span.start for span in spans]
    intervals = [(b - a).days for a, b in zip(starts, starts[1:])][-RECENT_CYCLES:]
    low, high = VALID_CYCLE_RANGE
    return [days for days in intervals if low <= days <= high]


def summarize_cycles(spans: list[PeriodSpan], today: date) -> CycleSummary:
    """spans 按开始日期升序。"""
    if not spans:
        return CycleSummary(
            has_data=False, cycle_day=None, phase=None, in_period=False,
            avg_cycle_days=DEFAULT_CYCLE_DAYS, avg_period_days=DEFAULT_PERIOD_DAYS,
            insufficient_data=True, next_start=None, next_start_earliest=None,
            next_start_latest=None, days_until_next=None, late_days=None, alerts=[],
        )

    valid = _valid_cycle_lengths(spans)
    insufficient = len(valid) < 2
    cycle_days = DEFAULT_CYCLE_DAYS if insufficient else round(sum(valid) / len(valid))
    ended = [(s.end - s.start).days + 1 for s in spans if s.end is not None][-RECENT_CYCLES:]
    period_days = round(sum(ended) / len(ended)) if ended else DEFAULT_PERIOD_DAYS

    last = spans[-1]
    cycle_day = (today - last.start).days + 1
    next_start = last.start + timedelta(days=cycle_days)
    earliest = last.start + timedelta(days=min(valid)) if not insufficient else None
    latest = last.start + timedelta(days=max(valid)) if not insufficient else None

    if last.end is None:
        in_period = cycle_day <= MAX_PERIOD_DAYS
    else:
        in_period = today <= last.end
    late_days = (today - next_start).days if today > next_start else None
    ovulation = next_start - timedelta(days=14)
    phase: Phase
    if in_period:
        phase = "menstrual"
    elif late_days is not None:
        phase = "late"
    elif abs((today - ovulation).days) <= 1:
        phase = "ovulation"
    elif today < ovulation:
        phase = "follicular"
    else:
        phase = "luteal"

    alerts: list[str] = []
    irregular = [days for days in valid if days < 21 or days > 35]
    if len(irregular) >= 2:
        alerts.append(f"最近有 {len(irregular)} 个周期短于 21 天或长于 35 天，可以咨询医生")
    if len(valid) >= 2 and max(valid) - min(valid) > 9:
        alerts.append(f"最近周期长度相差 {max(valid) - min(valid)} 天，波动较大，可以咨询医生")
    last_length = (last.end - last.start).days + 1 if last.end else cycle_day
    if last_length > 7 and (last.end is not None or in_period):
        alerts.append(f"最近一次经期持续 {last_length} 天（超过 7 天），可以咨询医生")
    if cycle_day - 1 > 60:
        alerts.append("距最近一次经期开始已超过 60 天，可以咨询医生")

    return CycleSummary(
        has_data=True,
        cycle_day=cycle_day,
        phase=phase,
        in_period=in_period,
        avg_cycle_days=cycle_days,
        avg_period_days=period_days,
        insufficient_data=insufficient,
        next_start=next_start,
        next_start_earliest=earliest,
        next_start_latest=latest,
        days_until_next=(next_start - today).days if late_days is None else None,
        late_days=late_days,
        alerts=alerts,
    )


# ---------- 接口 ----------


class CycleSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tracking_enabled: bool
    share_with_ai: bool
    adjust_targets: bool = Field(description="按周期调整热量参考并给饮食提示")


class CycleSettingsOut(CycleSettings):
    available: bool = Field(description="健康档案性别为女时才能开启")


class CycleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: date
    end_date: date | None = None
    flow: Flow | None = None
    symptoms: list[Symptom] = Field(default_factory=list, max_length=7)
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("symptoms")
    @classmethod
    def unique_symptoms(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class CyclePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_date: date | None = None
    end_date: date | None = None
    flow: Flow | None = None
    symptoms: list[Symptom] | None = Field(default=None, max_length=7)
    notes: str | None = Field(default=None, max_length=500)


class CycleOut(BaseModel):
    id: uuid.UUID
    start_date: date
    end_date: date | None
    flow: Flow | None
    symptoms: list[Symptom]
    notes: str | None


def _profile(db: Session, user_id: uuid.UUID) -> Profile | None:
    return db.scalar(select(Profile).where(Profile.user_id == user_id))


def _require_enabled(db: Session, user: User) -> Profile:
    profile = _profile(db, user.id)
    if profile is None or not profile.cycle_tracking_enabled or profile.sex != "female":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未开启周期记录")
    return profile


def _spans(db: Session, user_id: uuid.UUID) -> list[CyclePeriod]:
    return list(
        db.scalars(
            select(CyclePeriod).where(CyclePeriod.user_id == user_id).order_by(CyclePeriod.start_date)
        )
    )


def _owned(db: Session, user_id: uuid.UUID, cycle_id: uuid.UUID) -> CyclePeriod:
    period = db.scalar(
        select(CyclePeriod).where(CyclePeriod.id == cycle_id, CyclePeriod.user_id == user_id)
    )
    if period is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "记录不存在")
    return period


def _validate(db: Session, user: User, start: date, end: date | None, exclude: uuid.UUID | None) -> None:
    today = _today(user)
    if start > today or (end is not None and end > today):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "日期不能晚于今天")
    if end is not None:
        if end < start:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "结束日期不能早于开始日期")
        if (end - start).days + 1 > MAX_PERIOD_DAYS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"单次经期最长 {MAX_PERIOD_DAYS} 天")
    # 未结束的记录视为一直持续，因此也保证了“最多一条未结束的记录”
    new_end = end or date.max
    for other in _spans(db, user.id):
        if other.id == exclude:
            continue
        other_end = other.end_date or date.max
        if start <= other_end and other.start_date <= new_end:
            if other.end_date is None or end is None:
                raise HTTPException(status.HTTP_409_CONFLICT, "与一条未结束的经期记录重叠，请先结束或修改它")
            raise HTTPException(status.HTTP_409_CONFLICT, "与已有的经期记录日期重叠")


def _out(period: CyclePeriod) -> CycleOut:
    return CycleOut.model_validate(period, from_attributes=True)


@router.get("/cycle-settings")
def get_cycle_settings(user: CurrentUser, db: DbSession) -> CycleSettingsOut:
    profile = _profile(db, user.id)
    return CycleSettingsOut(
        tracking_enabled=bool(profile and profile.cycle_tracking_enabled),
        share_with_ai=bool(profile and profile.cycle_share_with_ai),
        adjust_targets=profile.cycle_adjust_targets if profile else True,
        available=bool(profile and profile.sex == "female"),
    )


@router.put("/cycle-settings")
def put_cycle_settings(body: CycleSettings, request: Request, user: CurrentUser, db: DbSession) -> CycleSettingsOut:
    profile = _profile(db, user.id)
    if body.tracking_enabled and (profile is None or profile.sex != "female"):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "健康档案性别为“女”时才能开启周期记录")
    if profile is None:
        profile = Profile(user_id=user.id)
        db.add(profile)
    ip = request.client.host if request.client else None
    # 审计只记录开关变化，不记录日期和症状
    changes = (
        ("cycle_tracking_enabled", body.tracking_enabled, "cycle_tracking"),
        ("cycle_share_with_ai", body.share_with_ai, "cycle_ai_share"),
        ("cycle_adjust_targets", body.adjust_targets, "cycle_adjust"),
    )
    for field, value, event in changes:
        current = getattr(profile, field)
        if current is None:
            current = field == "cycle_adjust_targets"
        if bool(current) != value:
            setattr(profile, field, value)
            add_audit_event(
                db, user_id=user.id, event_type=f"{event}_{'enabled' if value else 'disabled'}",
                outcome="success", ip_address=ip,
            )
    commit_with_tenant_context(db, user.id)
    return get_cycle_settings(user, db)


@router.get("/cycles")
def list_cycles(user: CurrentUser, db: DbSession) -> list[CycleOut]:
    _require_enabled(db, user)
    return [_out(period) for period in reversed(_spans(db, user.id))]


@router.get("/cycles/summary")
def cycles_summary(user: CurrentUser, db: DbSession) -> CycleSummary:
    profile = _require_enabled(db, user)
    spans = [PeriodSpan(p.start_date, p.end_date) for p in _spans(db, user.id)]
    summary = summarize_cycles(spans, _today(user))
    if profile.cycle_adjust_targets:
        if summary.phase == "luteal":
            summary.kcal_bonus = LUTEAL_KCAL_BONUS
            summary.tips = list(LUTEAL_TIPS)
        elif summary.phase == "menstrual":
            summary.tips = list(MENSTRUAL_TIPS)
    return summary


@router.post("/cycles", status_code=status.HTTP_201_CREATED)
def create_cycle(body: CycleIn, user: CurrentUser, db: DbSession) -> CycleOut:
    _require_enabled(db, user)
    _validate(db, user, body.start_date, body.end_date, exclude=None)
    period = CyclePeriod(user_id=user.id, **body.model_dump())
    db.add(period)
    commit_with_tenant_context(db, user.id)
    db.refresh(period)
    return _out(period)


@router.post("/cycles/start-today", status_code=status.HTTP_201_CREATED)
def start_today(user: CurrentUser, db: DbSession) -> CycleOut:
    _require_enabled(db, user)
    today = _today(user)
    _validate(db, user, today, None, exclude=None)
    period = CyclePeriod(user_id=user.id, start_date=today, symptoms=[])
    db.add(period)
    commit_with_tenant_context(db, user.id)
    db.refresh(period)
    return _out(period)


@router.post("/cycles/end-today")
def end_today(user: CurrentUser, db: DbSession) -> CycleOut:
    _require_enabled(db, user)
    ongoing = next((p for p in _spans(db, user.id) if p.end_date is None), None)
    if ongoing is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "没有进行中的经期")
    today = _today(user)
    _validate(db, user, ongoing.start_date, today, exclude=ongoing.id)
    ongoing.end_date = today
    commit_with_tenant_context(db, user.id)
    db.refresh(ongoing)
    return _out(ongoing)


@router.delete("/cycles", status_code=status.HTTP_204_NO_CONTENT)
def delete_all_cycles(user: CurrentUser, db: DbSession) -> None:
    _require_enabled(db, user)
    db.execute(delete(CyclePeriod).where(CyclePeriod.user_id == user.id))
    commit_with_tenant_context(db, user.id)


@router.get("/cycles/{cycle_id}")
def get_cycle(cycle_id: uuid.UUID, user: CurrentUser, db: DbSession) -> CycleOut:
    _require_enabled(db, user)
    return _out(_owned(db, user.id, cycle_id))


@router.patch("/cycles/{cycle_id}")
def patch_cycle(cycle_id: uuid.UUID, body: CyclePatch, user: CurrentUser, db: DbSession) -> CycleOut:
    _require_enabled(db, user)
    period = _owned(db, user.id, cycle_id)
    fields = body.model_fields_set
    if "start_date" in fields and body.start_date is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "开始日期不能为空")
    start = body.start_date if "start_date" in fields and body.start_date else period.start_date
    end = body.end_date if "end_date" in fields else period.end_date
    _validate(db, user, start, end, exclude=period.id)
    period.start_date = start
    period.end_date = end
    if "flow" in fields:
        period.flow = body.flow
    if "symptoms" in fields:
        period.symptoms = list(dict.fromkeys(body.symptoms or []))
    if "notes" in fields:
        period.notes = body.notes
    commit_with_tenant_context(db, user.id)
    db.refresh(period)
    return _out(period)


@router.delete("/cycles/{cycle_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cycle(cycle_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    _require_enabled(db, user)
    db.delete(_owned(db, user.id, cycle_id))
    commit_with_tenant_context(db, user.id)

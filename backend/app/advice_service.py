import json
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.dashboard import DailySummary, _daily_summary, _user_timezone
from app.models import Advice, Profile, User, UserNote

PROMPT_VERSION = "advice-v1"
PROMPT_PATH = Path(__file__).with_name("prompts") / "advice_v1.txt"
logger = logging.getLogger(__name__)


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    kind: Literal["diet", "exercise", "sleep", "records"]
    message: str = Field(min_length=1, max_length=300)
    severity: Literal["info", "attention"]


class AdviceAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Literal["diet", "exercise", "sleep", "general"]
    action: str = Field(min_length=1, max_length=300)
    rationale: str = Field(min_length=1, max_length=500)
    evidence_refs: list[str] = Field(default_factory=list, max_length=8)
    confidence: Literal["low", "medium", "high"]


class AdviceContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=500)
    actions: list[AdviceAction] = Field(min_length=1, max_length=5)
    limitations: list[str] = Field(default_factory=list, max_length=8)


class AdviceProviderError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ProviderResult:
    content: AdviceContent
    latency_ms: int
    prompt_tokens: int | None
    completion_tokens: int | None


UNSAFE_TERMS = {
    "诊断",
    "服用",
    "停药",
    "服药",
    "药物",
    "药品",
    "处方",
    "补充剂",
    "保健品",
    "减肥药",
    "注射",
    "剂量",
    "断食",
    "绝食",
    "泻药",
    "催吐",
    "极端节食",
    "危险运动",
    "diagnose",
    "diagnosis",
    "medicine",
    "medication",
    "prescription",
    "supplement",
    "dosage",
    "fasting",
}


def _average(values: list[float | int]) -> float | None:
    return round(sum(values) / len(values), 1) if values else None


def _advice_action_texts(raw_content: str | None) -> list[str]:
    if raw_content is None:
        return []
    try:
        return [
            action.action
            for action in AdviceContent.model_validate_json(raw_content).actions
        ]
    except ValidationError:
        return []


def derive_observations(
    days: list[DailySummary],
    target_kcal: int | None,
    *,
    current_date: date | None = None,
) -> list[Observation]:
    completed_days = (
        [day for day in days if day.date < current_date]
        if current_date is not None
        else days
    )
    recent_completed = completed_days[-7:]
    sleep_recent = days[-7:]
    observations: list[Observation] = []

    if target_kcal and target_kcal > 0 and len(recent_completed) >= 3:
        last_three = recent_completed[-3:]
        all_recorded = all(day.meal_count > 0 for day in last_three)
        below = sum(day.kcal < target_kcal for day in last_three)
        above = sum(day.kcal > target_kcal * 1.15 for day in last_three)
        if all_recorded and below == 3:
            observations.append(
                Observation(
                    id="kcal-below-target-3d",
                    kind="diet",
                    message="最近连续 3 天都有饮食记录，摄入均低于设定目标。",
                    severity="attention",
                )
            )
        elif all_recorded and above == 3:
            observations.append(
                Observation(
                    id="kcal-above-target-3d",
                    kind="diet",
                    message="最近连续 3 天都有饮食记录，摄入均超过设定目标的 115%。",
                    severity="attention",
                )
            )

    if len(recent_completed) >= 3 and all(
        day.exercise_minutes == 0 for day in recent_completed[-3:]
    ):
        observations.append(
            Observation(
                id="exercise-none-3d",
                kind="exercise",
                message="最近 3 天没有运动记录。",
                severity="attention",
            )
        )

    sleep_days = [day for day in sleep_recent if day.sleep_minutes > 0]
    if sum(day.sleep_minutes < 360 for day in sleep_days) >= 3:
        observations.append(
            Observation(
                id="sleep-under-6h-3d",
                kind="sleep",
                message="最近 7 天中至少有 3 天睡眠记录不足 6 小时。",
                severity="attention",
            )
        )
    current_day = (
        next((day for day in reversed(days) if day.date == current_date), None)
        if current_date is not None
        else (days[-1] if days else None)
    )
    historical_source = completed_days if current_date is not None else days[:-1]
    historical_sleep = [day.sleep_minutes for day in historical_source if day.sleep_minutes > 0]
    if current_day is not None and current_day.sleep_minutes > 0 and historical_sleep:
        baseline = _average(historical_sleep)
        if baseline is not None and current_day.sleep_minutes <= baseline - 60:
            observations.append(
                Observation(
                    id="sleep-below-baseline-1h",
                    kind="sleep",
                    message="最近一晚睡眠比近 30 天已有记录的平均值少至少 1 小时。",
                    severity="attention",
                )
            )

    meal_record_days = sum(day.meal_count > 0 for day in recent_completed)
    if meal_record_days < 4:
        observations.append(
            Observation(
                id="meal-records-under-4d",
                kind="records",
                message=f"最近 7 天只有 {meal_record_days} 天有饮食记录，趋势判断可能不完整。",
                severity="info",
            )
        )
    return observations


def build_advice_context(
    db: Session, user: User, *, kind: str, for_date: date
) -> tuple[dict[str, object], list[Observation]]:
    tz = _user_timezone(user)
    end_date = datetime.now(tz).date()
    start_date = end_date - timedelta(days=30)
    days = [
        _daily_summary(db, user, start_date + timedelta(days=offset), tz)
        for offset in range(31)
    ]
    completed_days = [day for day in days if day.date < end_date]
    profile = db.scalar(select(Profile).where(Profile.user_id == user.id))
    now = datetime.now(timezone.utc)
    notes = list(
        db.scalars(
            select(UserNote)
            .where(
                UserNote.user_id == user.id,
                (UserNote.expires_at.is_(None)) | (UserNote.expires_at > now),
            )
            .order_by(UserNote.created_at.desc())
            .limit(20)
        )
    )
    recent_feedback = list(
        db.scalars(
            select(Advice)
            .where(
                Advice.user_id == user.id,
                Advice.feedback.is_not(None),
                Advice.created_at >= now - timedelta(days=7),
            )
            .order_by(Advice.created_at.desc())
            .limit(10)
        )
    )
    weekly_plan: dict[str, object] | None = None
    if kind == "daily":
        weekly_candidates = list(
            db.scalars(
                select(Advice)
                .where(
                    Advice.user_id == user.id,
                    Advice.kind == "weekly",
                    Advice.status == "succeeded",
                    Advice.content_json.is_not(None),
                    or_(Advice.feedback.is_(None), Advice.feedback == "useful"),
                )
                .order_by(Advice.created_at.desc())
                .limit(10)
            )
        )
        for candidate in weekly_candidates:
            week_start = candidate.for_date.astimezone(tz).date()
            if week_start <= for_date < week_start + timedelta(days=7):
                try:
                    plan_content = AdviceContent.model_validate_json(candidate.content_json)
                except ValidationError:
                    continue
                weekly_plan = {
                    "for_week_starting": week_start.isoformat(),
                    "summary": plan_content.summary,
                    "actions": [
                        {
                            "category": action.category,
                            "action": action.action,
                            "rationale": action.rationale,
                        }
                        for action in plan_content.actions
                    ],
                }
                break
    target_kcal = profile.daily_kcal_target if profile else None
    observations = derive_observations(days, target_kcal, current_date=end_date)
    recorded_kcal = [day.kcal for day in completed_days if day.meal_count > 0]
    recorded_sleep = [day.sleep_minutes for day in completed_days if day.sleep_minutes > 0]
    age_band = None
    if profile and profile.birth_year:
        age = date.today().year - profile.birth_year
        age_band = f"{age // 10 * 10}-{age // 10 * 10 + 9}"

    context: dict[str, object] = {
        "schema_version": "1",
        "plan": {"kind": kind, "for_date": for_date.isoformat()},
        "profile": {
            "age_band": age_band,
            "sex": profile.sex if profile else None,
            "activity_level": profile.activity_level if profile else None,
            "daily_kcal_target": target_kcal,
            "dietary_preferences": profile.dietary_preferences if profile else None,
            "allergies": profile.allergies if profile else None,
        },
        "last_7_days": [day.model_dump(mode="json") for day in completed_days[-7:]],
        "today": days[-1].model_dump(mode="json"),
        "last_30_days": {
            "recorded_meal_days": sum(day.meal_count > 0 for day in completed_days),
            "average_kcal_on_recorded_days": _average(recorded_kcal),
            "total_exercise_minutes": sum(day.exercise_minutes for day in completed_days),
            "average_sleep_minutes_on_recorded_days": _average(recorded_sleep),
        },
        "user_notes": [
            {"category": note.category, "content": note.content} for note in notes
        ],
        "recent_feedback": [
            {
                "kind": item.kind,
                "feedback": item.feedback,
                "reason": item.feedback_reason,
                "actions": _advice_action_texts(item.content_json),
            }
            for item in recent_feedback
        ],
        "weekly_plan": weekly_plan,
        "observations": [item.model_dump() for item in observations],
        "notice": "健康习惯参考，不是医疗建议",
    }
    return context, observations


def _validate_safety(content: AdviceContent, allowed_refs: set[str]) -> AdviceContent:
    text = " ".join(
        [content.summary, *content.limitations]
        + [f"{item.action} {item.rationale}" for item in content.actions]
    ).lower()
    if any(term in text for term in UNSAFE_TERMS):
        raise AdviceProviderError("AI_UNSAFE_RESPONSE")
    for action in content.actions:
        if not set(action.evidence_refs).issubset(allowed_refs):
            raise AdviceProviderError("AI_INVALID_EVIDENCE")
        if not action.evidence_refs and action.confidence != "low":
            raise AdviceProviderError("AI_INVALID_CONFIDENCE")
    return content


def _validate_plan_timing(content: AdviceContent, context: dict[str, object]) -> None:
    plan = context.get("plan")
    today = context.get("today")
    if not isinstance(plan, dict) or not isinstance(today, dict):
        return
    target_date = plan.get("for_date")
    today_date = today.get("date")
    if not isinstance(target_date, str) or target_date == today_date:
        return
    forbidden = ("今天", "今日", "today", "this morning", "this evening")
    for action in content.actions:
        if any(term in action.action.lower() for term in forbidden):
            raise AdviceProviderError("AI_INVALID_PLAN_DATE")


def generate_advice(context: dict[str, object], settings: Settings) -> ProviderResult:
    if not settings.deepseek_api_key:
        raise AdviceProviderError("AI_NOT_CONFIGURED")
    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    payload = {
        "model": settings.deepseek_model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": "请根据以下 HealthOS 聚合摘要生成计划：\n"
                + json.dumps(context, ensure_ascii=False, separators=(",", ":")),
            },
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.3,
        "max_tokens": 1800,
    }
    started = time.monotonic()
    last_code = "AI_INVALID_RESPONSE"
    for _attempt in range(2):
        try:
            with httpx.Client(timeout=settings.deepseek_timeout_seconds) as client:
                response = client.post(
                    f"{settings.deepseek_base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
                    json=payload,
                )
                response.raise_for_status()
            body = response.json()
            content = AdviceContent.model_validate_json(body["choices"][0]["message"]["content"])
            allowed_refs = {item["id"] for item in context.get("observations", [])}  # type: ignore[index]
            _validate_safety(content, allowed_refs)
            _validate_plan_timing(content, context)
            usage = body.get("usage", {})
            return ProviderResult(
                content=content,
                latency_ms=round((time.monotonic() - started) * 1000),
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
            )
        except httpx.TimeoutException:
            last_code = "AI_TIMEOUT"
        except httpx.RequestError:
            last_code = "AI_CONNECTION_ERROR"
        except httpx.HTTPStatusError as exc:
            last_code = f"AI_HTTP_{exc.response.status_code}"
            if exc.response.status_code in {400, 401, 403}:
                break
        except AdviceProviderError:
            raise
        except (KeyError, TypeError, json.JSONDecodeError, ValidationError):
            last_code = "AI_INVALID_RESPONSE"
    raise AdviceProviderError(last_code)


def run_advice_job(advice_id: object, user_id: object) -> None:
    from app.audit import set_tenant_context
    from app.config import get_settings
    from app.db import SessionLocal

    with SessionLocal() as db:
        set_tenant_context(db, user_id)  # type: ignore[arg-type]
        advice = db.scalar(
            select(Advice).where(Advice.id == advice_id, Advice.user_id == user_id)
        )
        if advice is None:
            return
        try:
            result = generate_advice(json.loads(advice.context_json), get_settings())
            advice.status = "succeeded"
            advice.content_json = result.content.model_dump_json()
            advice.latency_ms = result.latency_ms
            advice.prompt_tokens = result.prompt_tokens
            advice.completion_tokens = result.completion_tokens
            advice.error_code = None
        except AdviceProviderError as exc:
            advice.status = "failed"
            advice.error_code = exc.code
        except Exception:
            logger.exception("Advice background job failed", extra={"advice_id": str(advice.id)})
            advice.status = "failed"
            advice.error_code = "AI_INTERNAL_ERROR"
        db.commit()

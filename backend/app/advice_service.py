import json
import logging
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.cycle import advice_cycle_context
from app.dashboard import DailySummary, _daily_summary, _user_timezone
from app.models import Advice, Profile, User, UserNote
from app.food_prefs import normalize_food_name, preference_context
from app.meal_ai import BUSY_STATUSES, _strip_code_fence, busy_backoff
from app.weights import weight_stats

PROMPT_VERSION = "advice-v4"
PROMPT_PATH = Path(__file__).with_name("prompts") / "advice_v4.txt"
logger = logging.getLogger(__name__)


class Observation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=64)
    kind: Literal["diet", "exercise", "sleep", "records", "weight", "cycle"]
    message: str = Field(min_length=1, max_length=300)
    severity: Literal["info", "attention"]


class AdviceAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: Literal["diet", "exercise", "sleep", "general"]
    action: str = Field(min_length=1, max_length=300)
    rationale: str = Field(min_length=1, max_length=500)
    evidence_refs: list[str] = Field(default_factory=list, max_length=8)
    confidence: Literal["low", "medium", "high"]


class MealPlanItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=50)
    portion: str = Field(min_length=1, max_length=30)
    approx_kcal: int = Field(ge=0, le=3000)


class MealPlanGroup(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meal_type: Literal["breakfast", "lunch", "dinner", "snack"]
    items: list[MealPlanItem] = Field(min_length=1, max_length=3)
    reason: str = Field(min_length=1, max_length=200)


class AdviceContent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=500)
    actions: list[AdviceAction] = Field(min_length=1, max_length=5)
    limitations: list[str] = Field(default_factory=list, max_length=8)
    # 仅每日建议使用；旧建议和周计划为空
    meal_plan: list[MealPlanGroup] = Field(default_factory=list, max_length=4)


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
    "止痛药",
    "止痛片",
    "布洛芬",
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
    "painkiller",
    "ibuprofen",
}

# 否定、免责声明或转介就医的语境中出现敏感词是安全的，例如“不建议断食”“请咨询医生诊断”。
_NEGATIONS = (
    "不建议", "不需要", "不能替代", "不能代替", "不构成", "不涉及",
    "不要", "不宜", "不必", "无需", "避免", "切勿", "请勿", "不是", "并非", "不作", "不做",
)
_FILLERS = ("进行", "采用", "使用", "尝试", "自行", "随意", "擅自", "盲目", "医疗", "任何")
_REFERRALS = ("医疗专业人员", "专业人员", "专业人士", "医疗机构", "医生", "医师")


def _alternation(words: Iterable[str]) -> str:
    return "|".join(re.escape(word) for word in sorted(words, key=len, reverse=True))


_TERMS_RE = _alternation(UNSAFE_TERMS)
_SAFE_CONTEXT_RE = re.compile(
    rf"(?:(?:{_alternation(_NEGATIONS)})(?:{_alternation(_FILLERS)})?|(?:{_alternation(_REFERRALS)})的?)"
    rf"(?:{_TERMS_RE})"
    rf"|\b(?:avoid|no|not|never|without)\s+(?:a\s+|any\s+)?(?:{_TERMS_RE})"
)


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


def derive_weight_observations(
    change_7d_kg: float | None, change_30d_kg: float | None
) -> list[Observation]:
    observations: list[Observation] = []
    if change_7d_kg is not None and change_7d_kg < -1.0:
        observations.append(
            Observation(
                id="weight-drop-fast-7d",
                kind="weight",
                message=f"最近 7 天体重下降 {abs(change_7d_kg)} kg，超过每周约 1 kg。",
                severity="attention",
            )
        )
    if change_30d_kg is not None and change_30d_kg > 2.0:
        observations.append(
            Observation(
                id="weight-gain-30d",
                kind="weight",
                message=f"最近 30 天体重上升 {change_30d_kg} kg。",
                severity="info",
            )
        )
    return observations


def derive_cycle_observations(
    cycle: dict[str, object] | None,
    completed_days: list[DailySummary],
    target_kcal: int | None,
) -> list[Observation]:
    if cycle is None:
        return []
    observations: list[Observation] = []
    phase = cycle.get("phase")
    cycle_day = cycle.get("cycle_day")
    symptoms = set(cycle.get("latest_period_symptoms") or [])  # type: ignore[arg-type]
    if (
        phase == "menstrual"
        and isinstance(cycle_day, int)
        and cycle_day <= 3
        and symptoms & {"cramps", "fatigue"}
    ):
        observations.append(
            Observation(
                id="cycle-early-period-discomfort",
                kind="cycle",
                message=f"目标日是经期第 {cycle_day} 天，本次经期记录了痛经或疲劳。",
                severity="attention",
            )
        )
    last_three = completed_days[-3:]
    if (
        phase == "luteal"
        and target_kcal
        and len(last_three) == 3
        and all(day.meal_count > 0 and day.kcal > target_kcal for day in last_three)
    ):
        observations.append(
            Observation(
                id="cycle-luteal-appetite",
                kind="cycle",
                message="处于经前阶段，最近 3 天摄入都高于目标；经前食欲增加很常见。",
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
    weight = weight_stats(db, user, end_date)
    observations += derive_weight_observations(weight.change_7d_kg, weight.change_30d_kg)
    # 周期层只在用户同意分享时出现；未同意时上下文里没有任何周期字段
    cycle = advice_cycle_context(db, user.id, max(for_date, end_date))
    observations += derive_cycle_observations(cycle, completed_days, target_kcal)
    recorded_kcal = [day.kcal for day in completed_days if day.meal_count > 0]
    recorded_sleep = [day.sleep_minutes for day in completed_days if day.sleep_minutes > 0]
    age_band = None
    if profile and profile.birth_year:
        age = date.today().year - profile.birth_year
        age_band = f"{age // 10 * 10}-{age // 10 * 10 + 9}"

    context: dict[str, object] = {
        "schema_version": "2",
        "plan": {"kind": kind, "for_date": for_date.isoformat()},
        "profile": {
            "age_band": age_band,
            "sex": profile.sex if profile else None,
            "activity_level": profile.activity_level if profile else None,
            "daily_kcal_target": target_kcal,
            "dietary_preferences": profile.dietary_preferences if profile else None,
            "allergies": profile.allergies if profile else None,
        },
        "weight": {
            "current_kg": weight.current.weight_kg if weight.current else None,
            "target_kg": profile.target_weight_kg if profile else None,
            "change_7d_kg": weight.change_7d_kg,
            "change_30d_kg": weight.change_30d_kg,
        },
        # 变化较少的层放在前面，尽量命中 DeepSeek 前缀缓存
        "food_preferences": preference_context(db, user.id),
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
    if cycle is not None:
        context["cycle"] = cycle
    return context, observations


def _validate_safety(content: AdviceContent, allowed_refs: set[str]) -> AdviceContent:
    text = " ".join(
        [content.summary, *content.limitations]
        + [f"{item.action} {item.rationale}" for item in content.actions]
        + [
            f"{group.reason} " + " ".join(item.name for item in group.items)
            for group in content.meal_plan
        ]
    ).lower()
    text = _SAFE_CONTEXT_RE.sub(" ", text)
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


_CYCLE_WORDS = ("生理期", "生理周期", "经期", "月经", "经前", "黄体期", "卵泡期", "排卵", "痛经")


def strip_cycle_mentions(content: AdviceContent, context: dict[str, object]) -> AdviceContent:
    """没有分享周期时不得提及：只在 limitations 里的直接删掉，写进正文则重新生成。"""
    if "cycle" in context:
        return content
    body = " ".join(
        [content.summary]
        + [f"{item.action} {item.rationale}" for item in content.actions]
        + [group.reason for group in content.meal_plan]
    )
    if any(word in body for word in _CYCLE_WORDS):
        raise AdviceProviderError("AI_UNSHARED_CYCLE")
    limitations = [
        item for item in content.limitations if not any(word in item for word in _CYCLE_WORDS)
    ]
    return content.model_copy(update={"limitations": limitations})


_ALLERGY_SPLIT_RE = re.compile(r"[，,、;；/\s]+|和|及|与|或")
_ALLERGY_SUFFIXES = ("过敏", "不耐受")
_NO_ALLERGY_WORDS = {"无", "没有", "暂无", "none", "no", "n/a"}


def allergy_keywords(allergies: str | None) -> list[str]:
    """把档案里的过敏描述拆成关键词，例如“花生、虾过敏”→ [花生, 虾]。"""
    if not allergies:
        return []
    keywords = []
    for raw in _ALLERGY_SPLIT_RE.split(normalize_food_name(allergies)):
        word = raw
        for suffix in _ALLERGY_SUFFIXES:
            word = word.removesuffix(suffix)
        if word and word not in _NO_ALLERGY_WORDS:
            keywords.append(word)
    return keywords


def filter_meal_plan(content: AdviceContent, context: dict[str, object]) -> AdviceContent:
    """代码层面的硬性过滤：周计划不带餐单；含过敏原或“不想再吃”的食物直接丢弃。"""
    plan = context.get("plan")
    if not isinstance(plan, dict) or plan.get("kind") != "daily":
        return content.model_copy(update={"meal_plan": []})
    profile = context.get("profile")
    prefs = context.get("food_preferences")
    allergens = allergy_keywords(profile.get("allergies") if isinstance(profile, dict) else None)
    dislikes = [normalize_food_name(d) for d in (prefs.get("dislikes", []) if isinstance(prefs, dict) else [])]

    def blocked(name: str) -> bool:
        food = normalize_food_name(name)
        if any(allergen in food for allergen in allergens):
            return True
        # 单字的“不想再吃”只做精确匹配，避免“鸡”误伤所有含鸡的菜
        return any(food == d or (len(d) >= 2 and d in food) for d in dislikes)

    groups = []
    for group in content.meal_plan:
        items = [item for item in group.items if not blocked(item.name)]
        if items:
            groups.append(group.model_copy(update={"items": items}))
    return content.model_copy(update={"meal_plan": groups})


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
        # 推理 token 也计入上限；餐单让输出变长
        "max_tokens": 4000,
    }
    started = time.monotonic()
    last_code = "AI_INVALID_RESPONSE"
    attempt = 0
    busy_retries = 0
    while attempt < 2:
        try:
            with httpx.Client(timeout=settings.deepseek_timeout_seconds) as client:
                response = client.post(
                    f"{settings.deepseek_base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {settings.deepseek_api_key}"},
                    json=payload,
                )
                response.raise_for_status()
            body = response.json()
            content = AdviceContent.model_validate_json(
                _strip_code_fence(body["choices"][0]["message"]["content"])
            )
            allowed_refs = {item["id"] for item in context.get("observations", [])}  # type: ignore[index]
            _validate_safety(content, allowed_refs)
            _validate_plan_timing(content, context)
            content = strip_cycle_mentions(content, context)
            content = filter_meal_plan(content, context)
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
            if exc.response.status_code in BUSY_STATUSES and busy_backoff(busy_retries):
                busy_retries += 1
                continue
        except AdviceProviderError as exc:
            # 输出校验失败（不安全、证据无效、日期不符）通常是偶发的，换一次生成再判断
            last_code = exc.code
        except (KeyError, TypeError, json.JSONDecodeError, ValidationError):
            last_code = "AI_INVALID_RESPONSE"
        attempt += 1
    raise AdviceProviderError(last_code)


def run_advice_job(advice_id: object, user_id: object) -> None:
    from app.audit import set_tenant_context
    from app.config import get_settings
    from app.db import SessionLocal

    def load_advice(db: Session) -> Advice | None:
        set_tenant_context(db, user_id)  # type: ignore[arg-type]
        return db.scalar(
            select(Advice).where(Advice.id == advice_id, Advice.user_id == user_id)
        )

    # 先读出上下文并释放连接，避免在等待 AI 响应期间长时间占用数据库连接
    with SessionLocal() as db:
        advice = load_advice(db)
        if advice is None:
            return
        context = json.loads(advice.context_json)

    result: ProviderResult | None = None
    error_code: str | None = None
    try:
        result = generate_advice(context, get_settings())
    except AdviceProviderError as exc:
        error_code = exc.code
    except Exception:
        logger.exception("Advice background job failed", extra={"advice_id": str(advice_id)})
        error_code = "AI_INTERNAL_ERROR"

    with SessionLocal() as db:
        advice = load_advice(db)
        if advice is None:
            return
        if result is not None:
            advice.status = "succeeded"
            advice.content_json = result.content.model_dump_json()
            advice.latency_ms = result.latency_ms
            advice.prompt_tokens = result.prompt_tokens
            advice.completion_tokens = result.completion_tokens
            advice.error_code = None
        else:
            advice.status = "failed"
            advice.error_code = error_code
        db.commit()

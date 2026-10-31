from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.deps import CurrentUser, DbSession
from app.models import Exercise, FoodItem, Meal, Profile, Sleep

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


class DailySummary(BaseModel):
    date: date
    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float
    meal_count: int
    exercise_minutes: int
    steps: int
    sleep_minutes: int
    sleep_quality: float | None


class TodayDashboard(BaseModel):
    date: date
    target_kcal: int | None
    kcal_completion_percent: int | None
    summary: DailySummary


class TrendDashboard(BaseModel):
    from_date: date
    to_date: date
    days: list[DailySummary] = Field(min_length=1, max_length=31)


def _user_timezone(user: CurrentUser) -> ZoneInfo:
    try:
        return ZoneInfo(user.timezone)
    except ZoneInfoNotFoundError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "账号时区无效，请先在设置中修改"
        ) from exc


def _utc_bounds(local_date: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    start = datetime.combine(local_date, time.min, tzinfo=tz).astimezone(timezone.utc)
    end = datetime.combine(local_date + timedelta(days=1), time.min, tzinfo=tz).astimezone(
        timezone.utc
    )
    return start, end


def _round(value: float) -> float:
    return round(value, 1)


def _daily_summary(
    db: DbSession, user: CurrentUser, local_date: date, tz: ZoneInfo
) -> DailySummary:
    start, end = _utc_bounds(local_date, tz)

    meals = list(
        db.scalars(
            select(Meal).where(
                Meal.user_id == user.id,
                Meal.status == "confirmed",
                Meal.eaten_at >= start,
                Meal.eaten_at < end,
            )
        )
    )
    meal_ids = [meal.id for meal in meals]
    food_items = (
        list(
            db.scalars(
                select(FoodItem).where(
                    FoodItem.user_id == user.id, FoodItem.meal_id.in_(meal_ids)
                )
            )
        )
        if meal_ids
        else []
    )

    exercises = list(
        db.scalars(
            select(Exercise).where(
                Exercise.user_id == user.id,
                Exercise.started_at >= start,
                Exercise.started_at < end,
            )
        )
    )
    sleeps = list(
        db.scalars(
            select(Sleep).where(
                Sleep.user_id == user.id,
                Sleep.ended_at >= start,
                Sleep.ended_at < end,
            )
        )
    )

    sleep_minutes = sum(
        max(0, round((sleep.ended_at - sleep.started_at).total_seconds() / 60))
        for sleep in sleeps
    )
    sleep_quality = (
        _round(sum(sleep.quality for sleep in sleeps) / len(sleeps)) if sleeps else None
    )
    return DailySummary(
        date=local_date,
        kcal=_round(sum(item.kcal for item in food_items)),
        protein_g=_round(sum(item.protein_g for item in food_items)),
        carbs_g=_round(sum(item.carbs_g for item in food_items)),
        fat_g=_round(sum(item.fat_g for item in food_items)),
        meal_count=len(meals),
        exercise_minutes=sum(exercise.minutes for exercise in exercises),
        steps=sum(exercise.steps or 0 for exercise in exercises),
        sleep_minutes=sleep_minutes,
        sleep_quality=sleep_quality,
    )


@router.get("/today")
def get_today_dashboard(
    user: CurrentUser,
    db: DbSession,
    on: date | None = Query(default=None, description="按账号时区计算的日期"),
) -> TodayDashboard:
    tz = _user_timezone(user)
    selected_date = on or datetime.now(tz).date()
    summary = _daily_summary(db, user, selected_date, tz)
    profile = db.scalar(select(Profile).where(Profile.user_id == user.id))
    target = profile.daily_kcal_target if profile else None
    completion = round(summary.kcal / target * 100) if target and target > 0 else None
    return TodayDashboard(
        date=selected_date,
        target_kcal=target,
        kcal_completion_percent=completion,
        summary=summary,
    )


@router.get("/trends")
def get_trend_dashboard(
    user: CurrentUser,
    db: DbSession,
    to: date | None = Query(default=None, description="结束日期（包含）"),
    days: int = Query(default=7, ge=1, le=31),
) -> TrendDashboard:
    tz = _user_timezone(user)
    end_date = to or datetime.now(tz).date()
    start_date = end_date - timedelta(days=days - 1)
    summaries = [
        _daily_summary(db, user, start_date + timedelta(days=offset), tz)
        for offset in range(days)
    ]
    return TrendDashboard(from_date=start_date, to_date=end_date, days=summaries)

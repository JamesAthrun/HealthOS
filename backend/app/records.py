import uuid
from datetime import datetime, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete, select

from app.audit import add_audit_event
from app.deps import CurrentUser, DbSession
from app.models import Exercise, FoodItem, Meal, Sleep
from app.repositories import get_owned_exercise, get_owned_meal, get_owned_sleep

router = APIRouter(prefix="/api", tags=["records"])


def _not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, "记录不存在")


def _audit_delete(db: DbSession, user: CurrentUser, request: Request) -> None:
    add_audit_event(
        db,
        user_id=user.id,
        event_type="record_deleted",
        outcome="success",
        ip_address=request.client.host if request.client else None,
    )


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("时间必须包含时区")
    return value


class FoodItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    quantity: float = Field(gt=0, le=100000)
    unit: str = Field(min_length=1, max_length=20)
    kcal: float = Field(ge=0, le=10000)
    protein_g: float = Field(default=0, ge=0, le=1000)
    carbs_g: float = Field(default=0, ge=0, le=1000)
    fat_g: float = Field(default=0, ge=0, le=1000)


class FoodItemOut(FoodItemIn):
    id: uuid.UUID


class MealIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    eaten_at: datetime
    meal_type: Literal["breakfast", "lunch", "dinner", "snack"]
    notes: str | None = Field(default=None, max_length=2000)
    food_items: list[FoodItemIn] = Field(min_length=1, max_length=50)

    _validate_eaten_at = field_validator("eaten_at")(_aware)


class MealPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    eaten_at: datetime | None = None
    meal_type: Literal["breakfast", "lunch", "dinner", "snack"] | None = None
    notes: str | None = Field(default=None, max_length=2000)
    food_items: list[FoodItemIn] | None = Field(default=None, min_length=1, max_length=50)

    @field_validator("eaten_at")
    @classmethod
    def validate_eaten_at(cls, value: datetime | None) -> datetime | None:
        return _aware(value) if value is not None else None


class MealOut(BaseModel):
    id: uuid.UUID
    eaten_at: datetime
    meal_type: str
    status: str
    notes: str | None
    food_items: list[FoodItemOut]
    created_at: datetime
    updated_at: datetime


def _replace_food_items(
    db: DbSession, meal: Meal, user_id: uuid.UUID, items: list[FoodItemIn]
) -> None:
    db.execute(
        delete(FoodItem).where(FoodItem.meal_id == meal.id, FoodItem.user_id == user_id)
    )
    for item in items:
        db.add(FoodItem(meal_id=meal.id, user_id=user_id, **item.model_dump()))


def _meal_out(db: DbSession, meal: Meal) -> MealOut:
    items = list(
        db.scalars(
            select(FoodItem)
            .where(FoodItem.meal_id == meal.id, FoodItem.user_id == meal.user_id)
            .order_by(FoodItem.name)
        )
    )
    return MealOut(
        id=meal.id,
        eaten_at=meal.eaten_at,
        meal_type=meal.meal_type,
        status=meal.status,
        notes=meal.notes,
        food_items=[FoodItemOut.model_validate(item, from_attributes=True) for item in items],
        created_at=meal.created_at,
        updated_at=meal.updated_at,
    )


@router.get("/meals")
def list_meals(user: CurrentUser, db: DbSession) -> list[MealOut]:
    meals = db.scalars(
        select(Meal).where(Meal.user_id == user.id).order_by(Meal.eaten_at.desc()).limit(100)
    )
    return [_meal_out(db, meal) for meal in meals]


@router.post("/meals", status_code=status.HTTP_201_CREATED)
def create_meal(body: MealIn, user: CurrentUser, db: DbSession) -> MealOut:
    meal = Meal(
        user_id=user.id,
        eaten_at=body.eaten_at,
        meal_type=body.meal_type,
        status="confirmed",
        notes=body.notes,
    )
    db.add(meal)
    db.flush()
    _replace_food_items(db, meal, user.id, body.food_items)
    db.commit()
    db.refresh(meal)
    return _meal_out(db, meal)


@router.get("/meals/{meal_id}")
def get_meal(meal_id: uuid.UUID, user: CurrentUser, db: DbSession) -> MealOut:
    meal = get_owned_meal(db, user.id, meal_id)
    if meal is None:
        raise _not_found()
    return _meal_out(db, meal)


@router.patch("/meals/{meal_id}")
def patch_meal(
    meal_id: uuid.UUID, body: MealPatch, user: CurrentUser, db: DbSession
) -> MealOut:
    meal = get_owned_meal(db, user.id, meal_id)
    if meal is None:
        raise _not_found()
    for field in ("eaten_at", "meal_type", "notes"):
        if field in body.model_fields_set:
            setattr(meal, field, getattr(body, field))
    if body.food_items is not None:
        _replace_food_items(db, meal, user.id, body.food_items)
    db.commit()
    db.refresh(meal)
    return _meal_out(db, meal)


@router.delete("/meals/{meal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_meal(
    meal_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> None:
    meal = get_owned_meal(db, user.id, meal_id)
    if meal is None:
        raise _not_found()
    db.delete(meal)
    _audit_delete(db, user, request)
    db.commit()


class ExerciseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1, max_length=50)
    started_at: datetime
    minutes: int = Field(ge=1, le=1440)
    intensity: Literal["low", "moderate", "high"]
    steps: int | None = Field(default=None, ge=0, le=200000)
    notes: str | None = Field(default=None, max_length=2000)

    _validate_started_at = field_validator("started_at")(_aware)


class ExercisePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str | None = Field(default=None, min_length=1, max_length=50)
    started_at: datetime | None = None
    minutes: int | None = Field(default=None, ge=1, le=1440)
    intensity: Literal["low", "moderate", "high"] | None = None
    steps: int | None = Field(default=None, ge=0, le=200000)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("started_at")
    @classmethod
    def validate_started_at(cls, value: datetime | None) -> datetime | None:
        return _aware(value) if value is not None else None


class ExerciseOut(ExerciseIn):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


def _exercise_out(exercise: Exercise) -> ExerciseOut:
    return ExerciseOut.model_validate(exercise, from_attributes=True)


@router.get("/exercises")
def list_exercises(user: CurrentUser, db: DbSession) -> list[ExerciseOut]:
    rows = db.scalars(
        select(Exercise)
        .where(Exercise.user_id == user.id)
        .order_by(Exercise.started_at.desc())
        .limit(100)
    )
    return [_exercise_out(row) for row in rows]


@router.post("/exercises", status_code=status.HTTP_201_CREATED)
def create_exercise(body: ExerciseIn, user: CurrentUser, db: DbSession) -> ExerciseOut:
    exercise = Exercise(user_id=user.id, **body.model_dump())
    db.add(exercise)
    db.commit()
    db.refresh(exercise)
    return _exercise_out(exercise)


@router.get("/exercises/{exercise_id}")
def get_exercise(
    exercise_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> ExerciseOut:
    exercise = get_owned_exercise(db, user.id, exercise_id)
    if exercise is None:
        raise _not_found()
    return _exercise_out(exercise)


@router.patch("/exercises/{exercise_id}")
def patch_exercise(
    exercise_id: uuid.UUID, body: ExercisePatch, user: CurrentUser, db: DbSession
) -> ExerciseOut:
    exercise = get_owned_exercise(db, user.id, exercise_id)
    if exercise is None:
        raise _not_found()
    for field in body.model_fields_set:
        setattr(exercise, field, getattr(body, field))
    db.commit()
    db.refresh(exercise)
    return _exercise_out(exercise)


@router.delete("/exercises/{exercise_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_exercise(
    exercise_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> None:
    exercise = get_owned_exercise(db, user.id, exercise_id)
    if exercise is None:
        raise _not_found()
    db.delete(exercise)
    _audit_delete(db, user, request)
    db.commit()


class SleepIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    started_at: datetime
    ended_at: datetime
    quality: int = Field(ge=1, le=5)
    notes: str | None = Field(default=None, max_length=2000)

    _validate_started_at = field_validator("started_at")(_aware)
    _validate_ended_at = field_validator("ended_at")(_aware)

    @model_validator(mode="after")
    def valid_range(self):
        if self.ended_at <= self.started_at:
            raise ValueError("睡眠结束时间必须晚于开始时间")
        if self.ended_at - self.started_at > timedelta(hours=24):
            raise ValueError("单次睡眠不能超过 24 小时")
        return self


class SleepPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    started_at: datetime | None = None
    ended_at: datetime | None = None
    quality: int | None = Field(default=None, ge=1, le=5)
    notes: str | None = Field(default=None, max_length=2000)

    @field_validator("started_at", "ended_at")
    @classmethod
    def validate_time(cls, value: datetime | None) -> datetime | None:
        return _aware(value) if value is not None else None


class SleepOut(SleepIn):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


def _sleep_out(sleep: Sleep) -> SleepOut:
    return SleepOut.model_validate(sleep, from_attributes=True)


@router.get("/sleeps")
def list_sleeps(user: CurrentUser, db: DbSession) -> list[SleepOut]:
    rows = db.scalars(
        select(Sleep).where(Sleep.user_id == user.id).order_by(Sleep.started_at.desc()).limit(100)
    )
    return [_sleep_out(row) for row in rows]


@router.post("/sleeps", status_code=status.HTTP_201_CREATED)
def create_sleep(body: SleepIn, user: CurrentUser, db: DbSession) -> SleepOut:
    sleep = Sleep(user_id=user.id, **body.model_dump())
    db.add(sleep)
    db.commit()
    db.refresh(sleep)
    return _sleep_out(sleep)


@router.get("/sleeps/{sleep_id}")
def get_sleep(sleep_id: uuid.UUID, user: CurrentUser, db: DbSession) -> SleepOut:
    sleep = get_owned_sleep(db, user.id, sleep_id)
    if sleep is None:
        raise _not_found()
    return _sleep_out(sleep)


@router.patch("/sleeps/{sleep_id}")
def patch_sleep(
    sleep_id: uuid.UUID, body: SleepPatch, user: CurrentUser, db: DbSession
) -> SleepOut:
    sleep = get_owned_sleep(db, user.id, sleep_id)
    if sleep is None:
        raise _not_found()
    started_at = body.started_at if body.started_at is not None else sleep.started_at
    ended_at = body.ended_at if body.ended_at is not None else sleep.ended_at
    if ended_at <= started_at or ended_at - started_at > timedelta(hours=24):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "睡眠时间范围无效")
    for field in body.model_fields_set:
        setattr(sleep, field, getattr(body, field))
    db.commit()
    db.refresh(sleep)
    return _sleep_out(sleep)


@router.delete("/sleeps/{sleep_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_sleep(
    sleep_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> None:
    sleep = get_owned_sleep(db, user.id, sleep_id)
    if sleep is None:
        raise _not_found()
    db.delete(sleep)
    _audit_delete(db, user, request)
    db.commit()

import re
import unicodedata
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import commit_with_tenant_context
from app.deps import CurrentUser, DbSession
from app.models import FoodItem, FoodPreference, Meal

router = APIRouter(prefix="/api", tags=["food preferences"])

MAX_PREFERENCES = 100
# 发给 AI 的数量上限：喜欢 / 不想再吃各 30 个，常吃 10 个
CONTEXT_LIMIT = 30
FREQUENT_LIMIT = 10
FREQUENT_DAYS = 30

Sentiment = Literal["like", "dislike"]


def normalize_food_name(name: str) -> str:
    """全角/半角统一（NFKC）、合并空白、去首尾空格、英文小写，用于去重和比较。"""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", name)).strip().lower()


class FoodPreferenceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    food_name: str = Field(min_length=1, max_length=50)
    sentiment: Sentiment

    @field_validator("food_name")
    @classmethod
    def normalized(cls, value: str) -> str:
        name = normalize_food_name(value)
        if not name:
            raise ValueError("食物名称不能为空")
        return name


class FoodPreferenceOut(BaseModel):
    id: uuid.UUID
    food_name: str
    sentiment: Sentiment
    updated_at: datetime


class FrequentFood(BaseModel):
    food_name: str
    count: int


def frequent_foods(db: Session, user_id: uuid.UUID, *, now: datetime | None = None) -> list[FrequentFood]:
    """最近 30 天已确认饮食中出现次数最多的食物（规范化后合并）。"""
    since = (now or datetime.now(timezone.utc)) - timedelta(days=FREQUENT_DAYS)
    names = db.scalars(
        select(FoodItem.name)
        .join(Meal, FoodItem.meal_id == Meal.id)
        .where(
            FoodItem.user_id == user_id,
            Meal.user_id == user_id,
            Meal.status == "confirmed",
            Meal.eaten_at >= since,
        )
    )
    counts = Counter(normalize_food_name(name) for name in names)
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:FREQUENT_LIMIT]
    return [FrequentFood(food_name=name, count=count) for name, count in ranked if name]


def preference_context(db: Session, user_id: uuid.UUID) -> dict[str, list[str]]:
    """建议上下文中的“食物偏好”层：只有食物名，不含每餐明细。"""
    prefs = list(
        db.scalars(
            select(FoodPreference)
            .where(FoodPreference.user_id == user_id)
            .order_by(FoodPreference.updated_at.desc(), FoodPreference.food_name)
        )
    )
    return {
        "likes": [p.food_name for p in prefs if p.sentiment == "like"][:CONTEXT_LIMIT],
        "dislikes": [p.food_name for p in prefs if p.sentiment == "dislike"][:CONTEXT_LIMIT],
        "frequent": [item.food_name for item in frequent_foods(db, user_id)],
    }


@router.get("/food-preferences")
def list_food_preferences(user: CurrentUser, db: DbSession) -> list[FoodPreferenceOut]:
    prefs = db.scalars(
        select(FoodPreference)
        .where(FoodPreference.user_id == user.id)
        .order_by(FoodPreference.updated_at.desc(), FoodPreference.food_name)
    )
    return [FoodPreferenceOut.model_validate(p, from_attributes=True) for p in prefs]


@router.put("/food-preferences")
def set_food_preference(
    body: FoodPreferenceIn, response: Response, user: CurrentUser, db: DbSession
) -> FoodPreferenceOut:
    pref = db.scalar(
        select(FoodPreference).where(
            FoodPreference.user_id == user.id, FoodPreference.food_name == body.food_name
        )
    )
    if pref is None:
        total = db.scalar(
            select(func.count()).select_from(FoodPreference).where(FoodPreference.user_id == user.id)
        )
        if (total or 0) >= MAX_PREFERENCES:
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"最多保存 {MAX_PREFERENCES} 条食物偏好，请先删除一些"
            )
        pref = FoodPreference(user_id=user.id, food_name=body.food_name, sentiment=body.sentiment)
        db.add(pref)
        response.status_code = status.HTTP_201_CREATED
    else:
        pref.sentiment = body.sentiment
    commit_with_tenant_context(db, user.id)
    db.refresh(pref)
    return FoodPreferenceOut.model_validate(pref, from_attributes=True)


@router.get("/food-preferences/frequent")
def list_frequent_foods(user: CurrentUser, db: DbSession) -> list[FrequentFood]:
    return frequent_foods(db, user.id)


@router.delete("/food-preferences/{preference_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_food_preference(preference_id: uuid.UUID, user: CurrentUser, db: DbSession) -> None:
    pref = db.scalar(
        select(FoodPreference).where(
            FoodPreference.id == preference_id, FoodPreference.user_id == user.id
        )
    )
    if pref is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "记录不存在")
    db.delete(pref)
    commit_with_tenant_context(db, user.id)

import uuid
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from app.audit import add_audit_event, commit_with_tenant_context
from app.deps import CurrentUser, DbSession
from app.models import Profile
from app.weights import _today, sync_profile_weight, upsert_weight

router = APIRouter(prefix="/api", tags=["profile"])

ACTIVITY_FACTORS = {
    "sedentary": 1.2,
    "light": 1.375,
    "moderate": 1.55,
    "active": 1.725,
}


class ProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    birth_year: int | None = Field(default=None, ge=1900)
    sex: Literal["male", "female"] | None = None
    height_cm: float | None = Field(default=None, ge=50, le=250)
    # 兼容旧客户端：传入时记为今天的体重记录；不传或为空则保持不变。新客户端用 /api/weights
    weight_kg: float | None = Field(default=None, ge=20, le=500)
    target_weight_kg: float | None = Field(default=None, ge=20, le=500)
    activity_level: Literal["sedentary", "light", "moderate", "active"] | None = None
    dietary_preferences: str | None = Field(default=None, max_length=1000)
    allergies: str | None = Field(default=None, max_length=1000)
    daily_kcal_target: int | None = Field(default=None, ge=1000, le=10000)

    @field_validator("birth_year")
    @classmethod
    def adults_only(cls, value: int | None) -> int | None:
        if value is not None and value > date.today().year - 18:
            raise ValueError("HealthOS 家庭版仅供成年人使用")
        return value


class ProfileOut(ProfileIn):
    user_id: uuid.UUID
    updated_at: datetime


class KcalReferenceOut(BaseModel):
    maintenance_kcal: int
    weight_loss_kcal: int | None
    bmi: float
    formula: str = "Mifflin-St Jeor"
    notice: str = "仅供健康习惯参考，不是医疗建议"


def _profile_out(profile: Profile) -> ProfileOut:
    return ProfileOut.model_validate(profile, from_attributes=True)


@router.get("/profile")
def get_profile(user: CurrentUser, db: DbSession) -> ProfileOut:
    profile = db.scalar(select(Profile).where(Profile.user_id == user.id))
    if profile is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "档案尚未创建")
    return _profile_out(profile)


@router.put("/profile")
def put_profile(body: ProfileIn, request: Request, user: CurrentUser, db: DbSession) -> ProfileOut:
    profile = db.scalar(select(Profile).where(Profile.user_id == user.id))
    if profile is None:
        profile = Profile(user_id=user.id)
        db.add(profile)
    # 热量目标已移到“营养目标”页；只有请求里带了这个字段才更新，避免保存档案时把它清空
    exclude = {"weight_kg"} if "daily_kcal_target" in body.model_fields_set else {"weight_kg", "daily_kcal_target"}
    for field, value in body.model_dump(exclude=exclude).items():
        setattr(profile, field, value)
    if body.weight_kg is not None and body.weight_kg != profile.weight_kg:
        upsert_weight(db, user.id, _today(user), body.weight_kg)
        sync_profile_weight(db, user.id)
    add_audit_event(
        db,
        user_id=user.id,
        event_type="profile_changed",
        outcome="success",
        ip_address=request.client.host if request.client else None,
    )
    commit_with_tenant_context(db, user.id)
    db.refresh(profile)
    return _profile_out(profile)


@router.get("/profile/kcal-reference")
def kcal_reference(user: CurrentUser, db: DbSession) -> KcalReferenceOut:
    profile = db.scalar(select(Profile).where(Profile.user_id == user.id))
    required = ("birth_year", "sex", "height_cm", "weight_kg", "activity_level")
    if profile is None or any(getattr(profile, field) is None for field in required):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "请先填写出生年份、性别、身高、体重和活动水平",
        )

    age = date.today().year - profile.birth_year  # type: ignore[operator]
    sex_offset = 5 if profile.sex == "male" else -161
    bmr = 10 * profile.weight_kg + 6.25 * profile.height_cm - 5 * age + sex_offset  # type: ignore[operator]
    maintenance = round(bmr * ACTIVITY_FACTORS[profile.activity_level])  # type: ignore[index]
    bmi = profile.weight_kg / ((profile.height_cm / 100) ** 2)  # type: ignore[operator]
    weight_loss = None
    if bmi >= 18.5:
        floor = 1500 if profile.sex == "male" else 1200
        weight_loss = max(floor, round(max(maintenance * 0.85, maintenance - 500)))
    return KcalReferenceOut(
        maintenance_kcal=maintenance,
        weight_loss_kcal=weight_loss,
        bmi=round(bmi, 1),
    )


class NutritionTargets(BaseModel):
    """每日营养目标；为空表示使用自动计算的参考值。"""

    model_config = ConfigDict(extra="forbid")

    daily_kcal_target: int | None = Field(default=None, ge=1000, le=10000)
    protein_g: float | None = Field(default=None, ge=10, le=400)
    carbs_g: float | None = Field(default=None, ge=20, le=1000)
    fat_g: float | None = Field(default=None, ge=10, le=400)
    fiber_g: float | None = Field(default=None, ge=5, le=100)
    sugar_max_g: float | None = Field(default=None, ge=0, le=300)
    sodium_max_mg: float | None = Field(default=None, ge=200, le=10000)


# API 字段 → profiles 列
_TARGET_COLUMNS = {
    "daily_kcal_target": "daily_kcal_target",
    "protein_g": "protein_target_g",
    "carbs_g": "carbs_target_g",
    "fat_g": "fat_target_g",
    "fiber_g": "fiber_target_g",
    "sugar_max_g": "sugar_max_g",
    "sodium_max_mg": "sodium_max_mg",
}


@router.get("/nutrition-targets")
def get_nutrition_targets(user: CurrentUser, db: DbSession) -> NutritionTargets:
    profile = db.scalar(select(Profile).where(Profile.user_id == user.id))
    if profile is None:
        return NutritionTargets()
    return NutritionTargets(**{field: getattr(profile, column) for field, column in _TARGET_COLUMNS.items()})


@router.put("/nutrition-targets")
def put_nutrition_targets(
    body: NutritionTargets, request: Request, user: CurrentUser, db: DbSession
) -> NutritionTargets:
    profile = db.scalar(select(Profile).where(Profile.user_id == user.id))
    if profile is None:
        profile = Profile(user_id=user.id)
        db.add(profile)
    for field, column in _TARGET_COLUMNS.items():
        setattr(profile, column, getattr(body, field))
    add_audit_event(
        db,
        user_id=user.id,
        event_type="profile_changed",
        outcome="success",
        ip_address=request.client.host if request.client else None,
    )
    commit_with_tenant_context(db, user.id)
    return get_nutrition_targets(user, db)

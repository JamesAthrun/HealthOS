import uuid
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from app.audit import add_audit_event
from app.deps import CurrentUser, DbSession
from app.models import Profile

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
    weight_kg: float | None = Field(default=None, ge=20, le=500)
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
    for field, value in body.model_dump().items():
        setattr(profile, field, value)
    add_audit_event(
        db,
        user_id=user.id,
        event_type="profile_changed",
        outcome="success",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
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

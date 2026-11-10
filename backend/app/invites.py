import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import aliased

from app.audit import add_audit_event
from app.deps import AdminUser, DbSession
from app.models import InviteCode, User
from app.security import hash_invite_code, new_invite_code, normalize_invite_code

router = APIRouter(prefix="/api/admin", tags=["admin"])

INVITE_DAYS = 7


class InviteCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    note: str | None = Field(default=None, max_length=50)


class InviteOut(BaseModel):
    id: uuid.UUID
    code_hint: str
    note: str | None
    status: Literal["active", "used", "expired", "revoked"]
    created_at: datetime
    expires_at: datetime
    used_at: datetime | None
    used_by_username: str | None


class InviteCreatedOut(InviteOut):
    # 明文只在生成时返回这一次
    code: str


def _status(invite: InviteCode, now: datetime) -> Literal["active", "used", "expired", "revoked"]:
    if invite.used_at is not None:
        return "used"
    if invite.revoked_at is not None:
        return "revoked"
    if invite.expires_at <= now:
        return "expired"
    return "active"


def _invite_out(invite: InviteCode, used_by_username: str | None, now: datetime) -> InviteOut:
    return InviteOut(
        id=invite.id,
        code_hint=invite.code_hint,
        note=invite.note,
        status=_status(invite, now),
        created_at=invite.created_at,
        expires_at=invite.expires_at,
        used_at=invite.used_at,
        used_by_username=used_by_username,
    )


@router.get("/invites")
def list_invites(admin: AdminUser, db: DbSession) -> list[InviteOut]:
    used_by = aliased(User)
    rows = db.execute(
        select(InviteCode, used_by.username)
        .outerjoin(used_by, used_by.id == InviteCode.used_by)
        .order_by(InviteCode.created_at.desc())
        .limit(50)
    ).all()
    now = datetime.now(timezone.utc)
    return [_invite_out(invite, username, now) for invite, username in rows]


@router.post("/invites", status_code=status.HTTP_201_CREATED)
def create_invite(
    body: InviteCreateIn, request: Request, admin: AdminUser, db: DbSession
) -> InviteCreatedOut:
    code = new_invite_code()
    now = datetime.now(timezone.utc)
    invite = InviteCode(
        code_hash=hash_invite_code(code),
        code_hint=normalize_invite_code(code)[-4:],
        note=(body.note or "").strip() or None,
        created_by=admin.id,
        created_at=now,
        expires_at=now + timedelta(days=INVITE_DAYS),
    )
    db.add(invite)
    add_audit_event(
        db,
        user_id=admin.id,
        event_type="invite_created",
        outcome="success",
        ip_address=request.client.host if request.client else None,
    )
    db.commit()
    return InviteCreatedOut(**_invite_out(invite, None, now).model_dump(), code=code)


@router.delete("/invites/{invite_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_invite(invite_id: uuid.UUID, admin: AdminUser, db: DbSession) -> None:
    invite = db.get(InviteCode, invite_id)
    if invite is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "邀请码不存在")
    if invite.used_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "邀请码已被使用，无法作废")
    if invite.revoked_at is None:
        invite.revoked_at = datetime.now(timezone.utc)
        db.commit()

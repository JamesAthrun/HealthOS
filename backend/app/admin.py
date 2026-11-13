import secrets
import shutil
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select

from app.audit import add_audit_event
from app.config import get_settings
from app.deps import AdminUser, DbSession
from app.models import User, UserSession
from app.security import hash_password

router = APIRouter(prefix="/api/admin", tags=["admin"])

# 临时密码：10 位小写字母和数字，去掉易混淆的 0/o/1/l/i，方便在手机上输入
_TEMP_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"


class AdminUserOut(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    is_admin: bool
    created_at: datetime
    last_login_at: datetime | None
    locked: bool


class ResetPasswordOut(BaseModel):
    temporary_password: str


class DeleteUserIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # 防误删：必须再输入一次用户名
    confirm_username: str = Field(min_length=1, max_length=32)


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _target(db: DbSession, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    return user


@router.get("/users")
def list_users(admin: AdminUser, db: DbSession) -> list[AdminUserOut]:
    last_login = (
        select(UserSession.user_id, func.max(UserSession.created_at).label("last_login_at"))
        .group_by(UserSession.user_id)
        .subquery()
    )
    rows = db.execute(
        select(User, last_login.c.last_login_at)
        .outerjoin(last_login, last_login.c.user_id == User.id)
        .order_by(User.created_at)
    ).all()
    now = datetime.now(timezone.utc)
    return [
        AdminUserOut(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            is_admin=user.is_admin,
            created_at=user.created_at,
            last_login_at=last_login_at,
            locked=bool(user.locked_until and user.locked_until > now),
        )
        for user, last_login_at in rows
    ]


@router.post("/users/{user_id}/reset-password")
def reset_password(user_id: uuid.UUID, request: Request, admin: AdminUser, db: DbSession) -> ResetPasswordOut:
    """生成临时密码（只显示这一次），解除锁定并让该用户所有设备重新登录。"""
    user = _target(db, user_id)
    if user.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "修改自己的密码请到“我的 → 修改密码”")
    temporary = "".join(secrets.choice(_TEMP_ALPHABET) for _ in range(10))
    user.password_hash = hash_password(temporary)
    user.failed_login_count = 0
    user.locked_until = None
    db.execute(delete(UserSession).where(UserSession.user_id == user.id))
    add_audit_event(db, user_id=admin.id, event_type="admin_password_reset", outcome="success", ip_address=_client_ip(request))
    db.commit()
    return ResetPasswordOut(temporary_password=temporary)


@router.post("/users/{user_id}/delete", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: uuid.UUID, body: DeleteUserIn, request: Request, admin: AdminUser, db: DbSession) -> None:
    """删除账号及其全部数据（记录、照片、建议等）。不能删除自己。"""
    user = _target(db, user_id)
    if user.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能删除自己的账号")
    if body.confirm_username.strip().lower() != user.username:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "输入的用户名不一致")
    deleted_id = user.id
    db.delete(user)
    add_audit_event(db, user_id=admin.id, event_type="admin_user_deleted", outcome="success", ip_address=_client_ip(request))
    db.commit()
    # 数据库记录已随账号级联删除，再清理这个账号的照片文件
    shutil.rmtree(get_settings().photo_dir / str(deleted_id), ignore_errors=True)

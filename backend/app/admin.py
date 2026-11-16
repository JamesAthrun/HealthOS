import os
import secrets
import shutil
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select, text

from app.ai_quota import local_midnight_utc
from app.audit import add_audit_event, set_tenant_context
from app.config import get_settings
from app.deps import AdminUser, DbSession
from app.models import AICall, Advice, AuditEvent, BackupRun, Meal, MealShare, User, UserSession
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


# ---------- 管理员总览 ----------

# 总览里显示的安全事件：登录失败、注册、改密码和管理员操作（不显示正常登录和会话过期）
SECURITY_EVENT_TYPES = ("registered", "password_changed", "admin_password_reset", "admin_user_deleted", "invite_created")


class UserUsage(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str
    is_admin: bool
    locked: bool
    last_login_at: datetime | None
    meals_today: int
    meals_7d: int
    ai_today: int
    ai_7d: int
    advice_7d: int


class AIOutcomeCount(BaseModel):
    outcome: str
    count: int


class AIStats(BaseModel):
    daily_limit: int
    calls_today: int
    calls_7d: int
    failed_7d: int
    avg_ms_7d: int | None
    slowest_ms_7d: int | None
    by_kind_7d: dict[str, int]
    failures_7d: list[AIOutcomeCount]
    advice_7d: int
    advice_failed_7d: int


class BackupInfo(BaseModel):
    finished_at: datetime
    ok: bool
    db_bytes: int | None
    photos_bytes: int | None
    message: str | None


class ServerStats(BaseModel):
    disk_total_bytes: int
    disk_free_bytes: int
    photos_bytes: int
    db_bytes: int | None
    last_backup: BackupInfo | None
    last_ok_backup_at: datetime | None


class SecurityEvent(BaseModel):
    created_at: datetime
    username: str
    event_type: str
    outcome: str
    ip_address: str | None


class DashboardOut(BaseModel):
    generated_at: datetime
    users: list[UserUsage]
    ai: AIStats
    server: ServerStats
    security_events: list[SecurityEvent]


def _count(db: DbSession, statement) -> int:  # type: ignore[no-untyped-def]
    return int(db.scalar(statement) or 0)


def _dir_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def _db_bytes(db: DbSession) -> int | None:
    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        return int(db.scalar(text("SELECT pg_database_size(current_database())")) or 0)
    database = bind.url.database
    return os.path.getsize(database) if database and os.path.isfile(database) else None


@router.get("/dashboard")
def dashboard(admin: AdminUser, db: DbSession) -> DashboardOut:
    """家庭成员的使用量、AI 调用、服务器状态和最近安全事件。只统计数量，不读取任何记录内容。"""
    now = datetime.now(timezone.utc)
    today = local_midnight_utc(admin)
    week = now - timedelta(days=7)
    users = list(db.scalars(select(User).order_by(User.created_at)))
    last_logins = dict(
        db.execute(select(UserSession.user_id, func.max(UserSession.created_at)).group_by(UserSession.user_id)).all()
    )

    usage: list[UserUsage] = []
    events: list[SecurityEvent] = []
    advice_7d = advice_failed_7d = 0
    try:
        for user in users:
            # 饮食、建议和安全事件有行级隔离：逐个切换到该用户，只取计数和事件元数据
            set_tenant_context(db, user.id)
            ai_today = _count(db, select(func.count(AICall.id)).where(AICall.user_id == user.id, AICall.started_at >= today))
            ai_7d = _count(db, select(func.count(AICall.id)).where(AICall.user_id == user.id, AICall.started_at >= week))
            user_advice = _count(db, select(func.count(Advice.id)).where(Advice.user_id == user.id, Advice.created_at >= week))
            advice_7d += user_advice
            advice_failed_7d += _count(
                db,
                select(func.count(Advice.id)).where(
                    Advice.user_id == user.id, Advice.created_at >= week, Advice.status == "failed"
                ),
            )
            usage.append(
                UserUsage(
                    id=user.id,
                    username=user.username,
                    display_name=user.display_name,
                    is_admin=user.is_admin,
                    locked=bool(user.locked_until and user.locked_until > now),
                    last_login_at=last_logins.get(user.id),
                    meals_today=_count(db, select(func.count(Meal.id)).where(Meal.user_id == user.id, Meal.created_at >= today)),
                    meals_7d=_count(db, select(func.count(Meal.id)).where(Meal.user_id == user.id, Meal.created_at >= week)),
                    ai_today=ai_today,
                    ai_7d=ai_7d,
                    advice_7d=user_advice,
                )
            )
            rows = db.scalars(
                select(AuditEvent)
                .where(
                    AuditEvent.user_id == user.id,
                    AuditEvent.created_at >= now - timedelta(days=14),
                    (AuditEvent.event_type.in_(SECURITY_EVENT_TYPES))
                    | ((AuditEvent.event_type == "login") & (AuditEvent.outcome == "denied")),
                )
                .order_by(AuditEvent.created_at.desc())
                .limit(30)
            )
            events.extend(
                SecurityEvent(
                    created_at=event.created_at,
                    username=user.username,
                    event_type=event.event_type,
                    outcome=event.outcome,
                    ip_address=event.ip_address,
                )
                for event in rows
            )
    finally:
        set_tenant_context(db, admin.id)

    kinds = dict(
        db.execute(select(AICall.kind, func.count(AICall.id)).where(AICall.started_at >= week).group_by(AICall.kind)).all()
    )
    outcomes = db.execute(
        select(AICall.outcome, func.count(AICall.id))
        .where(AICall.started_at >= week, AICall.outcome.not_in(("ok", "pending")))
        .group_by(AICall.outcome)
        .order_by(func.count(AICall.id).desc())
    ).all()
    avg_ms, max_ms = db.execute(
        select(func.avg(AICall.duration_ms), func.max(AICall.duration_ms)).where(
            AICall.started_at >= week, AICall.outcome == "ok"
        )
    ).one()

    settings = get_settings()
    photo_dir = settings.photo_dir
    photo_dir.mkdir(parents=True, exist_ok=True)
    disk = shutil.disk_usage(photo_dir)
    last_backup = db.scalar(select(BackupRun).order_by(BackupRun.finished_at.desc()).limit(1))
    last_ok_backup_at = db.scalar(select(func.max(BackupRun.finished_at)).where(BackupRun.ok.is_(True)))

    events.sort(key=lambda event: event.created_at, reverse=True)
    return DashboardOut(
        generated_at=now,
        users=usage,
        ai=AIStats(
            daily_limit=settings.ai_daily_limit,
            calls_today=sum(item.ai_today for item in usage),
            calls_7d=sum(kinds.values()),
            failed_7d=sum(count for _outcome, count in outcomes),
            avg_ms_7d=round(avg_ms) if avg_ms is not None else None,
            slowest_ms_7d=max_ms,
            by_kind_7d=kinds,
            failures_7d=[AIOutcomeCount(outcome=outcome, count=count) for outcome, count in outcomes],
            advice_7d=advice_7d,
            advice_failed_7d=advice_failed_7d,
        ),
        server=ServerStats(
            disk_total_bytes=disk.total,
            disk_free_bytes=disk.free,
            photos_bytes=_dir_size(str(photo_dir)),
            db_bytes=_db_bytes(db),
            last_backup=BackupInfo.model_validate(last_backup, from_attributes=True) if last_backup else None,
            last_ok_backup_at=last_ok_backup_at,
        ),
        security_events=events[:30],
    )


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
    share_ids = list(
        db.scalars(
            select(MealShare.id).where((MealShare.from_user_id == user.id) | (MealShare.to_user_id == user.id))
        )
    )
    db.delete(user)
    add_audit_event(db, user_id=admin.id, event_type="admin_user_deleted", outcome="success", ip_address=_client_ip(request))
    db.commit()
    # 数据库记录已随账号级联删除，再清理这个账号的照片文件和共餐邀请里的照片副本
    photo_dir = get_settings().photo_dir
    shutil.rmtree(photo_dir / str(deleted_id), ignore_errors=True)
    for share_id in share_ids:
        shutil.rmtree(photo_dir / "shares" / str(share_id), ignore_errors=True)

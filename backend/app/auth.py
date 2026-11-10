import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

from app.audit import add_audit_event
from app.config import get_settings
from app.deps import SESSION_COOKIE, CurrentUser, DbSession, SessionToken
from app.models import AuditEvent, InviteCode, User, UserSession
from app.repositories import get_owned_audit_event, list_owned_audit_events
from app.security import (
    MIN_PASSWORD_LENGTH,
    USERNAME_RE,
    hash_invite_code,
    hash_password,
    hash_session_token,
    login_limiter,
    needs_rehash,
    new_session_token,
    verify_password,
)

router = APIRouter(prefix="/api", tags=["account"])

MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15
LOGIN_FAILED = "用户名或密码错误，或尝试次数过多，请稍后再试"


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)


INVITE_INVALID = "邀请码无效、已使用或已过期"


class RegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    invite_code: str = Field(min_length=1, max_length=32)
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=128)
    display_name: str | None = Field(default=None, max_length=50)

    @field_validator("username")
    @classmethod
    def valid_username(cls, value: str) -> str:
        value = value.strip().lower()
        if not USERNAME_RE.match(value):
            raise ValueError("用户名只能包含小写字母、数字和下划线，长度 3–32")
        return value

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None


class UserOut(BaseModel):
    id: str
    username: str
    display_name: str
    is_admin: bool
    timezone: str
    locale: str


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=128)


class AccountSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=50)
    timezone: str = Field(min_length=1, max_length=64)
    locale: str = Field(pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$", max_length=16)

    @field_validator("display_name")
    @classmethod
    def clean_display_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("显示名称不能为空")
        return value

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("无效的时区") from exc
        return value


class AuditEventOut(BaseModel):
    id: uuid.UUID
    event_type: str
    outcome: str
    ip_address: str | None
    created_at: datetime


def to_audit_event_out(event: AuditEvent) -> AuditEventOut:
    return AuditEventOut.model_validate(event, from_attributes=True)


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def to_user_out(user: User) -> UserOut:
    return UserOut(
        id=str(user.id),
        username=user.username,
        display_name=user.display_name,
        is_admin=user.is_admin,
        timezone=user.timezone,
        locale=user.locale,
    )


def _set_session_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.session_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def _start_session(db: DbSession, user_id: uuid.UUID, now: datetime) -> str:
    token = new_session_token()
    db.add(
        UserSession(
            id_hash=hash_session_token(token),
            user_id=user_id,
            expires_at=now + timedelta(days=get_settings().session_days),
        )
    )
    return token


@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register(body: RegisterIn, request: Request, response: Response, db: DbSession) -> UserOut:
    client_ip = _client_ip(request) or "unknown"
    if not login_limiter.allow(client_ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "请求过于频繁，请稍后再试")

    now = datetime.now(timezone.utc)
    # 原子地占用邀请码：并发注册时只有一个请求能成功
    claimed = db.execute(
        update(InviteCode)
        .where(
            InviteCode.code_hash == hash_invite_code(body.invite_code),
            InviteCode.used_at.is_(None),
            InviteCode.revoked_at.is_(None),
            InviteCode.expires_at > now,
        )
        .values(used_at=now)
        .returning(InviteCode.id)
    ).scalar_one_or_none()
    if claimed is None:
        db.rollback()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, INVITE_INVALID)
    if db.scalar(select(User.id).where(User.username == body.username)):
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "用户名已被使用，换一个吧")

    user = User(
        username=body.username,
        display_name=body.display_name or body.username,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "用户名已被使用，换一个吧") from None
    db.execute(update(InviteCode).where(InviteCode.id == claimed).values(used_by=user.id))
    token = _start_session(db, user.id, now)
    add_audit_event(db, user_id=user.id, event_type="registered", outcome="success", ip_address=client_ip)
    db.commit()

    _set_session_cookie(response, token)
    return to_user_out(user)


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response, db: DbSession) -> UserOut:
    client_ip = _client_ip(request) or "unknown"
    if not login_limiter.allow(client_ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "请求过于频繁，请稍后再试")

    now = datetime.now(timezone.utc)
    user = db.scalar(select(User).where(User.username == body.username.strip().lower()))

    password_ok = verify_password(user.password_hash if user else None, body.password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, LOGIN_FAILED)
    if user.locked_until and user.locked_until > now:
        add_audit_event(
            db,
            user_id=user.id,
            event_type="login",
            outcome="denied",
            ip_address=client_ip,
        )
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, LOGIN_FAILED)
    if not password_ok:
        user.failed_login_count += 1
        if user.failed_login_count >= MAX_FAILED_LOGINS:
            user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
            user.failed_login_count = 0
        add_audit_event(
            db,
            user_id=user.id,
            event_type="login",
            outcome="denied",
            ip_address=client_ip,
        )
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, LOGIN_FAILED)

    user.failed_login_count = 0
    user.locked_until = None
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)

    token = _start_session(db, user.id, now)
    add_audit_event(
        db,
        user_id=user.id,
        event_type="login",
        outcome="success",
        ip_address=client_ip,
    )
    db.execute(delete(UserSession).where(UserSession.user_id == user.id, UserSession.expires_at <= now))
    db.commit()

    _set_session_cookie(response, token)
    return to_user_out(user)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    request: Request,
    response: Response,
    db: DbSession,
    session_token: SessionToken = None,
) -> None:
    if session_token:
        user_id = db.scalar(
            select(UserSession.user_id).where(
                UserSession.id_hash == hash_session_token(session_token)
            )
        )
        if user_id:
            add_audit_event(
                db,
                user_id=user_id,
                event_type="logout",
                outcome="success",
                ip_address=_client_ip(request),
            )
        db.execute(delete(UserSession).where(UserSession.id_hash == hash_session_token(session_token)))
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me")
def me(user: CurrentUser) -> UserOut:
    return to_user_out(user)


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: ChangePasswordIn,
    request: Request,
    user: CurrentUser,
    db: DbSession,
    session_token: SessionToken = None,
) -> None:
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "当前密码不正确")
    user.password_hash = hash_password(body.new_password)
    # 修改密码后，除当前设备外的其他会话全部失效
    db.execute(
        delete(UserSession).where(
            UserSession.user_id == user.id,
            UserSession.id_hash != hash_session_token(session_token or ""),
        )
    )
    add_audit_event(
        db,
        user_id=user.id,
        event_type="password_changed",
        outcome="success",
        ip_address=_client_ip(request),
    )
    db.commit()


@router.put("/me/settings")
def update_account_settings(
    body: AccountSettingsIn,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> UserOut:
    user.display_name = body.display_name
    user.timezone = body.timezone
    user.locale = body.locale
    add_audit_event(
        db,
        user_id=user.id,
        event_type="settings_changed",
        outcome="success",
        ip_address=_client_ip(request),
    )
    db.commit()
    return to_user_out(user)


@router.get("/me/audit-events")
def audit_events(user: CurrentUser, db: DbSession) -> list[AuditEventOut]:
    return [to_audit_event_out(event) for event in list_owned_audit_events(db, user.id)]


@router.get("/me/audit-events/{event_id}")
def audit_event(event_id: uuid.UUID, user: CurrentUser, db: DbSession) -> AuditEventOut:
    event = get_owned_audit_event(db, user.id, event_id)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "记录不存在")
    return to_audit_event_out(event)

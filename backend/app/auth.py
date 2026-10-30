from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Cookie, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.config import get_settings
from app.deps import SESSION_COOKIE, CurrentUser, DbSession
from app.models import User, UserSession
from app.security import (
    MIN_PASSWORD_LENGTH,
    hash_password,
    hash_session_token,
    login_limiter,
    needs_rehash,
    new_session_token,
    verify_password,
)

router = APIRouter(prefix="/api")

MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15
LOGIN_FAILED = "用户名或密码错误，或尝试次数过多，请稍后再试"


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    id: str
    username: str
    display_name: str
    is_admin: bool
    timezone: str


class ChangePasswordIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=128)


def to_user_out(user: User) -> UserOut:
    return UserOut(
        id=str(user.id),
        username=user.username,
        display_name=user.display_name,
        is_admin=user.is_admin,
        timezone=user.timezone,
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


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response, db: DbSession) -> UserOut:
    client_ip = request.client.host if request.client else "unknown"
    if not login_limiter.allow(client_ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "请求过于频繁，请稍后再试")

    now = datetime.now(timezone.utc)
    user = db.scalar(select(User).where(User.username == body.username.strip().lower()))

    password_ok = verify_password(user.password_hash if user else None, body.password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, LOGIN_FAILED)
    if user.locked_until and user.locked_until > now:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, LOGIN_FAILED)
    if not password_ok:
        user.failed_login_count += 1
        if user.failed_login_count >= MAX_FAILED_LOGINS:
            user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
            user.failed_login_count = 0
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, LOGIN_FAILED)

    user.failed_login_count = 0
    user.locked_until = None
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)

    token = new_session_token()
    db.add(
        UserSession(
            id_hash=hash_session_token(token),
            user_id=user.id,
            expires_at=now + timedelta(days=get_settings().session_days),
        )
    )
    db.execute(delete(UserSession).where(UserSession.user_id == user.id, UserSession.expires_at <= now))
    db.commit()

    _set_session_cookie(response, token)
    return to_user_out(user)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    db: DbSession,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> None:
    if session_token:
        db.execute(delete(UserSession).where(UserSession.id_hash == hash_session_token(session_token)))
        db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")


@router.get("/me")
def me(user: CurrentUser) -> UserOut:
    return to_user_out(user)


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    body: ChangePasswordIn,
    user: CurrentUser,
    db: DbSession,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
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
    db.commit()

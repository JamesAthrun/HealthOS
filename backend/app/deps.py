from datetime import datetime, timezone
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import User, UserSession
from app.security import hash_session_token

SESSION_COOKIE = "healthos_session"

DbSession = Annotated[Session, Depends(get_db)]


def get_current_user(
    db: DbSession,
    session_token: Annotated[str | None, Cookie(alias=SESSION_COOKIE)] = None,
) -> User:
    if session_token:
        row = db.execute(
            select(User, UserSession)
            .join(UserSession, UserSession.user_id == User.id)
            .where(UserSession.id_hash == hash_session_token(session_token))
        ).first()
        if row and row.UserSession.expires_at > datetime.now(timezone.utc):
            return row.User
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "请先登录")


CurrentUser = Annotated[User, Depends(get_current_user)]

from datetime import datetime, timezone
from typing import Annotated

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyCookie
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import add_audit_event, set_tenant_context
from app.db import get_db
from app.models import User, UserSession
from app.security import hash_session_token

SESSION_COOKIE = "healthos_session"
session_cookie = APIKeyCookie(
    name=SESSION_COOKIE,
    scheme_name="SessionCookie",
    description="登录成功后由服务端设置的 HttpOnly 会话 Cookie。",
    auto_error=False,
)

DbSession = Annotated[Session, Depends(get_db)]
SessionToken = Annotated[str | None, Security(session_cookie)]


def get_current_user(
    db: DbSession,
    session_token: SessionToken = None,
) -> User:
    if session_token:
        row = db.execute(
            select(User, UserSession)
            .join(UserSession, UserSession.user_id == User.id)
            .where(UserSession.id_hash == hash_session_token(session_token))
        ).first()
        if row and row.UserSession.expires_at > datetime.now(timezone.utc):
            set_tenant_context(db, row.User.id)
            return row.User
        if row:
            add_audit_event(
                db,
                user_id=row.User.id,
                event_type="session_expired",
                outcome="denied",
                ip_address=None,
            )
            db.delete(row.UserSession)
            db.commit()
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "请先登录")


CurrentUser = Annotated[User, Depends(get_current_user)]

import uuid

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import AuditEvent


def set_tenant_context(db: Session, user_id: uuid.UUID) -> None:
    """为当前 PostgreSQL 事务设置 RLS 用户；SQLite 测试由应用层过滤兜底。"""

    if db.bind is not None and db.bind.dialect.name == "postgresql":
        db.execute(
            text("SELECT set_config('app.current_user_id', :user_id, true)"),
            {"user_id": str(user_id)},
        )


def add_audit_event(
    db: Session,
    *,
    user_id: uuid.UUID,
    event_type: str,
    outcome: str,
    ip_address: str | None,
) -> AuditEvent:
    set_tenant_context(db, user_id)
    event = AuditEvent(
        user_id=user_id,
        event_type=event_type,
        outcome=outcome,
        ip_address=ip_address,
    )
    db.add(event)
    return event

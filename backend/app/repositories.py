import uuid

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.models import AuditEvent, Exercise, Meal, Sleep


def owned_audit_events(user_id: uuid.UUID) -> Select[tuple[AuditEvent]]:
    """所有租户资源查询必须从认证主体派生 owner 条件。"""

    return select(AuditEvent).where(AuditEvent.user_id == user_id)


def list_owned_audit_events(db: Session, user_id: uuid.UUID, *, limit: int = 50) -> list[AuditEvent]:
    statement = owned_audit_events(user_id).order_by(AuditEvent.created_at.desc()).limit(limit)
    return list(db.scalars(statement))


def get_owned_audit_event(db: Session, user_id: uuid.UUID, event_id: uuid.UUID) -> AuditEvent | None:
    return db.scalar(owned_audit_events(user_id).where(AuditEvent.id == event_id))


def get_owned_meal(db: Session, user_id: uuid.UUID, resource_id: uuid.UUID) -> Meal | None:
    return db.scalar(select(Meal).where(Meal.id == resource_id, Meal.user_id == user_id))


def get_owned_exercise(db: Session, user_id: uuid.UUID, resource_id: uuid.UUID) -> Exercise | None:
    return db.scalar(
        select(Exercise).where(Exercise.id == resource_id, Exercise.user_id == user_id)
    )


def get_owned_sleep(db: Session, user_id: uuid.UUID, resource_id: uuid.UUID) -> Sleep | None:
    return db.scalar(select(Sleep).where(Sleep.id == resource_id, Sleep.user_id == user_id))

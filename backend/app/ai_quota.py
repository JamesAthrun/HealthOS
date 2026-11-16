import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, time as dtime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select, update

from app.config import get_settings
from app.dashboard import _user_timezone
from app.db import SessionLocal
from app.meal_ai import AIProviderError
from app.models import AICall, User


def local_midnight_utc(user: User) -> datetime:
    """用户时区的今天 0 点（UTC 表示）。"""
    tz = _user_timezone(user)
    today = datetime.now(tz).date()
    return datetime.combine(today, dtime.min, tzinfo=tz).astimezone(timezone.utc)


class DailyAIQuota:
    """每人每天（按用户时区）调用 AI 识别/估算的次数上限，防止费用失控。管理员不受限制。

    次数来自 ai_calls 表，重启后也不会清零。
    """

    def consume(self, user: User) -> None:
        limit = get_settings().ai_daily_limit
        if limit <= 0 or user.is_admin:
            return
        with SessionLocal() as db:
            used = db.scalar(
                select(func.count(AICall.id)).where(
                    AICall.user_id == user.id, AICall.started_at >= local_midnight_utc(user)
                )
            ) or 0
        if used >= limit:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"今天的 AI 识别次数已用完（每天 {limit} 次），明天再试，或先手动填写",
            )


ai_quota = DailyAIQuota()


@contextmanager
def tracked_ai_call(user: User, kind: str) -> Iterator[None]:
    """记录一次 AI 调用的类型、耗时和结果（用独立会话写入，不影响请求里的事务）。"""
    call_id = uuid.uuid4()
    started = time.monotonic()
    with SessionLocal() as db:
        db.add(AICall(id=call_id, user_id=user.id, kind=kind, started_at=datetime.now(timezone.utc), outcome="pending"))
        db.commit()
    outcome = "error"
    try:
        yield
        outcome = "ok"
    except AIProviderError as exc:
        outcome = exc.code[:32]
        raise
    finally:
        with SessionLocal() as db:
            db.execute(
                update(AICall)
                .where(AICall.id == call_id)
                .values(outcome=outcome, duration_ms=int((time.monotonic() - started) * 1000))
            )
            db.commit()

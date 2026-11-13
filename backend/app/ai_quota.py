import threading
import uuid
from datetime import date, datetime

from fastapi import HTTPException, status

from app.config import get_settings
from app.dashboard import _user_timezone
from app.models import User


class DailyAIQuota:
    """每人每天（按用户时区）调用 AI 识别/估算的次数上限，防止费用失控。

    单进程内存计数：重启后当天重新计数，对家庭使用足够。管理员不受限制。
    """

    def __init__(self) -> None:
        self._counts: dict[tuple[uuid.UUID, date], int] = {}
        self._lock = threading.Lock()

    def consume(self, user: User) -> None:
        limit = get_settings().ai_daily_limit
        if limit <= 0 or user.is_admin:
            return
        today = datetime.now(_user_timezone(user)).date()
        key = (user.id, today)
        with self._lock:
            # 只保留今天前后的计数，避免无限增长
            for stale in [k for k in self._counts if abs((k[1] - today).days) > 1]:
                del self._counts[stale]
            used = self._counts.get(key, 0)
            if used >= limit:
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    f"今天的 AI 识别次数已用完（每天 {limit} 次），明天再试，或先手动填写",
                )
            self._counts[key] = used + 1

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()


ai_quota = DailyAIQuota()

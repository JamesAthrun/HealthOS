import hashlib
import secrets
import threading
import time
from collections import defaultdict, deque

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

# 默认参数 memory_cost=64 MiB；2 GB 服务器上单进程同时只处理少量登录，足够
_hasher = PasswordHasher()
# 用户不存在时也做一次校验，避免通过响应时间判断用户名是否存在
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))

MIN_PASSWORD_LENGTH = 8


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str | None, password: str) -> bool:
    try:
        return _hasher.verify(password_hash or _DUMMY_HASH, password) and password_hash is not None
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


class RateLimiter:
    """单进程内存限流：每个 key 在 window 秒内最多 limit 次。"""

    def __init__(self, limit: int, window_seconds: float) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


login_limiter = RateLimiter(limit=10, window_seconds=60)

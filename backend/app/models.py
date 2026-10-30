import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String, func
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from app.db import Base


class UTCDateTime(TypeDecorator[datetime]):
    """始终返回带 UTC 时区的时间。SQLite 不保存时区，读取时补上 UTC。"""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("必须使用带时区的时间")
        return value.astimezone(timezone.utc) if value is not None else None

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(32), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(50))
    is_admin: Mapped[bool] = mapped_column(default=False)
    timezone: Mapped[str] = mapped_column(String(64), default="Asia/Shanghai")
    failed_login_count: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now())


class UserSession(Base):
    __tablename__ = "sessions"

    # 只保存会话令牌的 SHA-256，数据库泄露也无法直接冒用会话
    id_hash: Mapped[bytes] = mapped_column(LargeBinary(32), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)

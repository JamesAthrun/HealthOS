from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy import URL, make_url

# 本机开发时读取仓库根目录的 .env；容器中通过环境变量传入
BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_ENV_FILE = BACKEND_DIR.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_ENV_FILE, extra="ignore")

    # 测试或高级部署可直接传 DATABASE_URL；Compose 使用下面的独立字段，避免把特殊字符密码拼进 URL。
    database_url: str | None = None
    postgres_host: str | None = None
    postgres_port: int = 5432
    postgres_db: str = "healthos"
    postgres_user: str = "healthos_app"
    postgres_password: str | None = None
    # 本地 http 开发设为 false；上线 HTTPS 后必须为 true
    cookie_secure: bool = False
    session_days: int = 30
    # 允许发起写请求的来源（逗号分隔），用于 CSRF 防护
    allowed_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000", "http://localhost:8080"]

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip().rstrip("/") for item in value.split(",") if item.strip()]
        return value

    @property
    def sqlalchemy_database_url(self) -> URL:
        if self.database_url:
            return make_url(self.database_url)
        if self.postgres_host:
            if not self.postgres_password:
                raise ValueError("POSTGRES_HOST 已设置，但 POSTGRES_PASSWORD 为空")
            return URL.create(
                "postgresql+psycopg",
                username=self.postgres_user,
                password=self.postgres_password,
                host=self.postgres_host,
                port=self.postgres_port,
                database=self.postgres_db,
            )
        return URL.create("sqlite", database=(BACKEND_DIR / "healthos_dev.sqlite3").as_posix())


@lru_cache
def get_settings() -> Settings:
    return Settings()

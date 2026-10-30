from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# 本机开发时读取仓库根目录的 .env；容器中通过环境变量传入
BACKEND_DIR = Path(__file__).resolve().parents[1]
ROOT_ENV_FILE = BACKEND_DIR.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_ENV_FILE, extra="ignore")

    # 默认使用本地 SQLite 文件，开发时不需要安装数据库；部署时由 compose 传入 PostgreSQL 地址
    database_url: str = f"sqlite:///{(BACKEND_DIR / 'healthos_dev.sqlite3').as_posix()}"
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


@lru_cache
def get_settings() -> Settings:
    return Settings()

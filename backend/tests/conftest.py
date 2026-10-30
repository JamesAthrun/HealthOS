import os
import tempfile
from pathlib import Path

# 默认用临时 SQLite 文件，不需要安装数据库；
# 部署前可用 TEST_DATABASE_URL=postgresql+psycopg://... 对 PostgreSQL 再跑一遍
_TMP_DIR = tempfile.mkdtemp(prefix="healthos-test-")
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", f"sqlite:///{(Path(_TMP_DIR) / 'test.sqlite3').as_posix()}"
)
# 必须在导入 app 之前设置，app.db 在导入时创建 engine
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ["ALLOWED_ORIGINS"] = "http://testserver"
os.environ["COOKIE_SECURE"] = "false"

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import make_url  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import User  # noqa: E402
from app.security import hash_password, login_limiter  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parents[1]
ORIGIN = "http://testserver"


def _ensure_postgres_test_database() -> None:
    import psycopg

    url = make_url(TEST_DATABASE_URL)
    admin_dsn = url.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False)
    with psycopg.connect(admin_dsn, autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (url.database,)).fetchone():
            conn.execute(f'CREATE DATABASE "{url.database}"')


@pytest.fixture(scope="session", autouse=True)
def database() -> None:
    if TEST_DATABASE_URL.startswith("postgresql"):
        _ensure_postgres_test_database()
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    # 先降到空库再升级，同时验证迁移脚本的 upgrade/downgrade 都能执行
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_tables() -> None:
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
    login_limiter.reset()


def create_user(username: str, password: str = "password123", display_name: str | None = None) -> User:
    with SessionLocal() as db:
        user = User(
            username=username,
            display_name=display_name or username,
            password_hash=hash_password(password),
        )
        db.add(user)
        db.commit()
        return user


def new_client() -> TestClient:
    return TestClient(app, headers={"Origin": ORIGIN})


def login(client: TestClient, username: str, password: str = "password123"):
    return client.post("/api/auth/login", json={"username": username, "password": password})

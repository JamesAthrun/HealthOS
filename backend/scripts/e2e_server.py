"""端到端测试用的后端：临时 SQLite 数据库 + 两个测试账号，监听 127.0.0.1:8100。

由 frontend/playwright.config.ts 自动启动，也可以手动运行：
    python scripts/e2e_server.py
不会碰本地开发库 healthos_dev.sqlite3。
"""

import os
import sys
import tempfile
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

TMP = Path(tempfile.mkdtemp(prefix="healthos-e2e-"))
PORT = int(os.environ.get("E2E_API_PORT", "8100"))
FRONTEND_ORIGIN = os.environ.get("E2E_FRONTEND_ORIGIN", "http://localhost:3100")

os.environ["DATABASE_URL"] = f"sqlite:///{(TMP / 'e2e.sqlite3').as_posix()}"
os.environ["PHOTO_DIR"] = str(TMP / "photos")
os.environ["ALLOWED_ORIGINS"] = f"{FRONTEND_ORIGIN},{FRONTEND_ORIGIN.replace('localhost', '127.0.0.1')}"
os.environ["COOKIE_SECURE"] = "false"
# 端到端测试不调用真实 AI
os.environ["DEEPSEEK_API_KEY"] = ""

import uvicorn  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

E2E_USERS = (
    # 用户名, 密码, 显示名, 是否管理员
    ("e2eadmin", "e2e-admin-pass", "测试管理员", True),
    ("e2euser", "e2e-user-pass", "测试用户", False),
)


def main() -> None:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    command.upgrade(cfg, "head")

    from app.db import SessionLocal
    from app.main import app
    from app.models import User
    from app.security import hash_password

    with SessionLocal() as db:
        for username, password, display_name, is_admin in E2E_USERS:
            db.add(User(username=username, password_hash=hash_password(password), display_name=display_name, is_admin=is_admin))
        db.commit()
    print(f"e2e api on http://127.0.0.1:{PORT} (data in {TMP})", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()

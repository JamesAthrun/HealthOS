"""管理员命令行：创建账号、重置密码。

用法：
    python -m app.cli create-user <用户名> [--display-name 名字] [--admin]
    python -m app.cli reset-password <用户名>
"""

import argparse
import getpass
import re
import sys

from sqlalchemy import delete, select

from app.db import SessionLocal
from app.models import User, UserSession
from app.security import MIN_PASSWORD_LENGTH, hash_password

USERNAME_RE = re.compile(r"^[a-z0-9_]{3,32}$")


def _prompt_password() -> str:
    while True:
        password = getpass.getpass("密码：")
        if len(password) < MIN_PASSWORD_LENGTH:
            print(f"密码至少 {MIN_PASSWORD_LENGTH} 位")
            continue
        if password != getpass.getpass("再输入一次："):
            print("两次输入不一致")
            continue
        return password


def create_user(username: str, display_name: str | None, is_admin: bool) -> int:
    username = username.strip().lower()
    if not USERNAME_RE.match(username):
        print("用户名只能包含小写字母、数字和下划线，长度 3–32")
        return 1
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.username == username)):
            print(f"用户 {username} 已存在")
            return 1
        password = _prompt_password()
        db.add(
            User(
                username=username,
                display_name=display_name or username,
                password_hash=hash_password(password),
                is_admin=is_admin,
            )
        )
        db.commit()
    print(f"已创建用户 {username}")
    return 0


def reset_password(username: str) -> int:
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == username.strip().lower()))
        if user is None:
            print(f"用户 {username} 不存在")
            return 1
        user.password_hash = hash_password(_prompt_password())
        user.failed_login_count = 0
        user.locked_until = None
        db.execute(delete(UserSession).where(UserSession.user_id == user.id))
        db.commit()
    print(f"已重置 {username} 的密码，该用户所有设备需要重新登录")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create-user", help="创建账号")
    p_create.add_argument("username")
    p_create.add_argument("--display-name")
    p_create.add_argument("--admin", action="store_true")

    p_reset = sub.add_parser("reset-password", help="重置密码")
    p_reset.add_argument("username")

    args = parser.parse_args()
    if args.command == "create-user":
        return create_user(args.username, args.display_name, args.admin)
    return reset_password(args.username)


if __name__ == "__main__":
    sys.exit(main())

"""daily weight logs and target weight

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-03
"""

import uuid
from datetime import timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

# 只声明需要的列，让 SQLAlchemy 在 SQLite/PostgreSQL 上都把时间转换成 datetime
_users = sa.table("users", sa.column("id", sa.Uuid()), sa.column("timezone", sa.String()))
_profiles = sa.table(
    "profiles",
    sa.column("user_id", sa.Uuid()),
    sa.column("weight_kg", sa.Float()),
    sa.column("updated_at", sa.DateTime(timezone=True)),
)
_weight_logs = sa.table(
    "weight_logs",
    sa.column("id", sa.Uuid()),
    sa.column("user_id", sa.Uuid()),
    sa.column("measured_on", sa.Date()),
    sa.column("weight_kg", sa.Float()),
)


def _owner_policy(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_owner ON {table}
        USING (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)
        WITH CHECK (user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid)
        """
    )


def _copy_profile_weights(is_postgres: bool) -> None:
    """把已有的 profiles.weight_kg 转为第一条体重记录。

    profiles 和 weight_logs 都受 FORCE RLS 约束（迁移角色也一样），
    所以在 PostgreSQL 上逐个用户设置 app.current_user_id 后再读写。
    """
    bind = op.get_bind()
    users = bind.execute(sa.select(_users.c.id, _users.c.timezone)).all()
    for user_id, tz_name in users:
        if is_postgres:
            bind.execute(
                sa.text("SELECT set_config('app.current_user_id', :uid, true)"),
                {"uid": str(user_id)},
            )
        row = bind.execute(
            sa.select(_profiles.c.weight_kg, _profiles.c.updated_at).where(
                _profiles.c.user_id == user_id
            )
        ).first()
        if row is None or row.weight_kg is None:
            continue
        try:
            tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            tz = ZoneInfo("Asia/Shanghai")
        updated_at = row.updated_at
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        bind.execute(
            sa.insert(_weight_logs).values(
                id=uuid.uuid4(),
                user_id=user_id,
                measured_on=updated_at.astimezone(tz).date(),
                weight_kg=row.weight_kg,
            )
        )
    if is_postgres:
        bind.execute(sa.text("SELECT set_config('app.current_user_id', '', true)"))


def upgrade() -> None:
    is_postgres = op.get_bind().dialect.name == "postgresql"
    with op.batch_alter_table("profiles") as batch_op:
        batch_op.add_column(sa.Column("target_weight_kg", sa.Float(), nullable=True))

    op.create_table(
        "weight_logs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("measured_on", sa.Date(), nullable=False),
        sa.Column("weight_kg", sa.Float(), nullable=False),
        sa.Column("waist_cm", sa.Float(), nullable=True),
        sa.Column("body_fat_pct", sa.Float(), nullable=True),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "measured_on", name="uq_weight_logs_user_day"),
    )
    op.create_index("ix_weight_logs_user_id", "weight_logs", ["user_id"])

    if is_postgres:
        _owner_policy("weight_logs")
    _copy_profile_weights(is_postgres)


def downgrade() -> None:
    op.drop_index("ix_weight_logs_user_id", table_name="weight_logs")
    op.drop_table("weight_logs")
    with op.batch_alter_table("profiles") as batch_op:
        batch_op.drop_column("target_weight_kg")

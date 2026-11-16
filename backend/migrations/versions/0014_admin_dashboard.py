"""admin dashboard: ai_calls and backup_runs

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-13
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 只记录调用元数据（谁、什么类型、何时、耗时、结果），不含饮食内容，因此不加行级隔离
    op.create_table(
        "ai_calls",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(32), nullable=False),
    )
    op.create_index("ix_ai_calls_user_started", "ai_calls", ["user_id", "started_at"])
    op.create_index("ix_ai_calls_started_at", "ai_calls", ["started_at"])
    op.create_table(
        "backup_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("db_bytes", sa.BigInteger(), nullable=True),
        sa.Column("photos_bytes", sa.BigInteger(), nullable=True),
        sa.Column("message", sa.String(200), nullable=True),
    )
    op.create_index("ix_backup_runs_finished_at", "backup_runs", ["finished_at"])


def downgrade() -> None:
    op.drop_index("ix_backup_runs_finished_at", table_name="backup_runs")
    op.drop_table("backup_runs")
    op.drop_index("ix_ai_calls_started_at", table_name="ai_calls")
    op.drop_index("ix_ai_calls_user_started", table_name="ai_calls")
    op.drop_table("ai_calls")

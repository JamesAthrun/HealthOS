"""cycle tracking: profile switches and cycle_periods

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-09
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


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


def upgrade() -> None:
    with op.batch_alter_table("profiles") as batch_op:
        batch_op.add_column(
            sa.Column("cycle_tracking_enabled", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch_op.add_column(
            sa.Column("cycle_share_with_ai", sa.Boolean(), server_default=sa.false(), nullable=False)
        )
        batch_op.add_column(
            sa.Column("cycle_adjust_targets", sa.Boolean(), server_default=sa.true(), nullable=False)
        )

    op.create_table(
        "cycle_periods",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("flow", sa.String(8), nullable=True),
        sa.Column("symptoms", sa.JSON(), nullable=False),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_cycle_periods_user_id", "cycle_periods", ["user_id"])
    op.create_index("ix_cycle_periods_user_start", "cycle_periods", ["user_id", "start_date"])
    if op.get_bind().dialect.name == "postgresql":
        _owner_policy("cycle_periods")


def downgrade() -> None:
    op.drop_index("ix_cycle_periods_user_start", table_name="cycle_periods")
    op.drop_index("ix_cycle_periods_user_id", table_name="cycle_periods")
    op.drop_table("cycle_periods")
    with op.batch_alter_table("profiles") as batch_op:
        batch_op.drop_column("cycle_adjust_targets")
        batch_op.drop_column("cycle_share_with_ai")
        batch_op.drop_column("cycle_tracking_enabled")

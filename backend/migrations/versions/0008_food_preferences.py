"""food preferences (like / dislike)

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-03
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
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
    op.create_table(
        "food_preferences",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("food_name", sa.String(50), nullable=False),
        sa.Column("sentiment", sa.String(8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "food_name", name="uq_food_preferences_user_food"),
    )
    op.create_index("ix_food_preferences_user_id", "food_preferences", ["user_id"])
    if op.get_bind().dialect.name == "postgresql":
        _owner_policy("food_preferences")


def downgrade() -> None:
    op.drop_index("ix_food_preferences_user_id", table_name="food_preferences")
    op.drop_table("food_preferences")

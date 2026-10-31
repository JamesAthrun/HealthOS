"""profiles and manual health records

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-31
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _owner_policy(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {table}_owner ON {table}
        USING (
            user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
        )
        WITH CHECK (
            user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
        )
        """
    )


def upgrade() -> None:
    op.create_table(
        "profiles",
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("birth_year", sa.Integer(), nullable=True),
        sa.Column("sex", sa.String(16), nullable=True),
        sa.Column("height_cm", sa.Float(), nullable=True),
        sa.Column("weight_kg", sa.Float(), nullable=True),
        sa.Column("activity_level", sa.String(16), nullable=True),
        sa.Column("dietary_preferences", sa.Text(), nullable=True),
        sa.Column("allergies", sa.Text(), nullable=True),
        sa.Column("daily_kcal_target", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "meals",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("eaten_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("meal_type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_meals_user_id", "meals", ["user_id"])
    op.create_index("ix_meals_user_eaten", "meals", ["user_id", "eaten_at"])
    op.create_table(
        "food_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("meal_id", sa.Uuid(), sa.ForeignKey("meals.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("quantity", sa.Float(), nullable=False),
        sa.Column("unit", sa.String(20), nullable=False),
        sa.Column("kcal", sa.Float(), nullable=False),
        sa.Column("protein_g", sa.Float(), nullable=False),
        sa.Column("carbs_g", sa.Float(), nullable=False),
        sa.Column("fat_g", sa.Float(), nullable=False),
    )
    op.create_index("ix_food_items_meal_id", "food_items", ["meal_id"])
    op.create_index("ix_food_items_user_id", "food_items", ["user_id"])
    op.create_index("ix_food_items_user_meal", "food_items", ["user_id", "meal_id"])
    op.create_table(
        "exercises",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("intensity", sa.String(16), nullable=False),
        sa.Column("steps", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_exercises_user_id", "exercises", ["user_id"])
    op.create_index("ix_exercises_user_started", "exercises", ["user_id", "started_at"])
    op.create_table(
        "sleeps",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quality", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_sleeps_user_id", "sleeps", ["user_id"])
    op.create_index("ix_sleeps_user_started", "sleeps", ["user_id", "started_at"])

    if op.get_bind().dialect.name == "postgresql":
        for table in ("profiles", "meals", "food_items", "exercises", "sleeps"):
            _owner_policy(table)


def downgrade() -> None:
    op.drop_index("ix_sleeps_user_started", table_name="sleeps")
    op.drop_index("ix_sleeps_user_id", table_name="sleeps")
    op.drop_table("sleeps")
    op.drop_index("ix_exercises_user_started", table_name="exercises")
    op.drop_index("ix_exercises_user_id", table_name="exercises")
    op.drop_table("exercises")
    op.drop_index("ix_food_items_user_meal", table_name="food_items")
    op.drop_index("ix_food_items_user_id", table_name="food_items")
    op.drop_index("ix_food_items_meal_id", table_name="food_items")
    op.drop_table("food_items")
    op.drop_index("ix_meals_user_eaten", table_name="meals")
    op.drop_index("ix_meals_user_id", table_name="meals")
    op.drop_table("meals")
    op.drop_table("profiles")

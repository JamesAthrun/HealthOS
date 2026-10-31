"""private meal photos and AI drafts

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-31
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
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
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("ai_consent_at", sa.DateTime(timezone=True), nullable=True))

    op.create_table(
        "meal_photos",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("storage_key", sa.String(255), nullable=False, unique=True),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("content_type", sa.String(32), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("user_id", "sha256", name="uq_meal_photos_user_sha256"),
    )
    op.create_index("ix_meal_photos_user_id", "meal_photos", ["user_id"])
    op.create_index("ix_meal_photos_user_created", "meal_photos", ["user_id", "created_at"])

    with op.batch_alter_table("meals") as batch_op:
        batch_op.add_column(sa.Column("photo_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_meals_photo_id", "meal_photos", ["photo_id"], ["id"], ondelete="SET NULL"
        )
        batch_op.create_index("ix_meals_photo_id", ["photo_id"])

    op.create_table(
        "meal_analyses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("photo_id", sa.Uuid(), sa.ForeignKey("meal_photos.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("confirmed_meal_id", sa.Uuid(), sa.ForeignKey("meals.id", ondelete="SET NULL"), nullable=True, unique=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_meal_analyses_user_id", "meal_analyses", ["user_id"])
    op.create_index("ix_meal_analyses_photo_id", "meal_analyses", ["photo_id"])
    op.create_index("ix_meal_analyses_user_created", "meal_analyses", ["user_id", "created_at"])

    if op.get_bind().dialect.name == "postgresql":
        _owner_policy("meal_photos")
        _owner_policy("meal_analyses")


def downgrade() -> None:
    op.drop_index("ix_meal_analyses_user_created", table_name="meal_analyses")
    op.drop_index("ix_meal_analyses_photo_id", table_name="meal_analyses")
    op.drop_index("ix_meal_analyses_user_id", table_name="meal_analyses")
    op.drop_table("meal_analyses")
    with op.batch_alter_table("meals") as batch_op:
        batch_op.drop_index("ix_meals_photo_id")
        batch_op.drop_constraint("fk_meals_photo_id", type_="foreignkey")
        batch_op.drop_column("photo_id")
    op.drop_index("ix_meal_photos_user_created", table_name="meal_photos")
    op.drop_index("ix_meal_photos_user_id", table_name="meal_photos")
    op.drop_table("meal_photos")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("ai_consent_at")

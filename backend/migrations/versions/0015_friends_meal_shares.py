"""friends and shared meals: friendships, meal_shares, meals.shared_from_id

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-16
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 这两张表连接两个账户，不加行级隔离；API 只返回当前用户是参与方的行
    op.create_table(
        "friendships",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("pair_key", sa.String(73), nullable=False, unique=True),
        sa.Column("requester_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("addressee_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_friendships_requester_id", "friendships", ["requester_id"])
    op.create_index("ix_friendships_addressee_id", "friendships", ["addressee_id"])
    op.create_table(
        "meal_shares",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("from_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("to_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_meal_id", sa.Uuid(), nullable=True),
        sa.Column("created_meal_id", sa.Uuid(), nullable=True),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("photo_count", sa.Integer(), nullable=False),
        sa.Column("ratio", sa.Float(), nullable=False),
        sa.Column("source_ratio", sa.Float(), server_default="1", nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("update_pending", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_meal_shares_from_user_id", "meal_shares", ["from_user_id"])
    op.create_index("ix_meal_shares_to_user_id", "meal_shares", ["to_user_id"])
    op.create_index("ix_meal_shares_source_meal_id", "meal_shares", ["source_meal_id"])
    with op.batch_alter_table("meals") as batch_op:
        batch_op.add_column(sa.Column("shared_from_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_meals_shared_from_id", "meal_shares", ["shared_from_id"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    with op.batch_alter_table("meals") as batch_op:
        batch_op.drop_constraint("fk_meals_shared_from_id", type_="foreignkey")
        batch_op.drop_column("shared_from_id")
    op.drop_index("ix_meal_shares_source_meal_id", table_name="meal_shares")
    op.drop_index("ix_meal_shares_to_user_id", table_name="meal_shares")
    op.drop_index("ix_meal_shares_from_user_id", table_name="meal_shares")
    op.drop_table("meal_shares")
    op.drop_index("ix_friendships_addressee_id", table_name="friendships")
    op.drop_index("ix_friendships_requester_id", table_name="friendships")
    op.drop_table("friendships")

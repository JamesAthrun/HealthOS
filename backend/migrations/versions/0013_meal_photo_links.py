"""link all photos of a meal: meal_photos.meal_id

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-11
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("meal_photos") as batch_op:
        batch_op.add_column(sa.Column("meal_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_meal_photos_meal_id", "meals", ["meal_id"], ["id"], ondelete="SET NULL"
        )
        batch_op.create_index("ix_meal_photos_meal_id", ["meal_id"])
    # 以前只记了每餐的第一张照片（meals.photo_id），先把它们关联上
    op.execute(
        """
        UPDATE meal_photos SET meal_id = (
            SELECT meals.id FROM meals WHERE meals.photo_id = meal_photos.id LIMIT 1
        )
        WHERE EXISTS (SELECT 1 FROM meals WHERE meals.photo_id = meal_photos.id)
        """
    )


def downgrade() -> None:
    with op.batch_alter_table("meal_photos") as batch_op:
        batch_op.drop_index("ix_meal_photos_meal_id")
        batch_op.drop_constraint("fk_meal_photos_meal_id", type_="foreignkey")
        batch_op.drop_column("meal_id")

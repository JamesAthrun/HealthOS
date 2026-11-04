"""optional fiber / sugar / sodium on food items

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-04
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

COLUMNS = ("fiber_g", "sugar_g", "sodium_mg")


def upgrade() -> None:
    for name in COLUMNS:
        op.add_column("food_items", sa.Column(name, sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("food_items") as batch:
        for name in COLUMNS:
            batch.drop_column(name)

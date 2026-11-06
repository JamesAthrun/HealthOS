"""nutrition targets on profiles

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

COLUMNS = ("protein_target_g", "carbs_target_g", "fat_target_g", "fiber_target_g", "sugar_max_g", "sodium_max_mg")


def upgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        for name in COLUMNS:
            batch.add_column(sa.Column(name, sa.Float(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("profiles") as batch:
        for name in reversed(COLUMNS):
            batch.drop_column(name)

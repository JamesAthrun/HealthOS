"""link remembered feedback to its source advice

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-01
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("user_notes") as batch_op:
        batch_op.add_column(sa.Column("source_advice_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_user_notes_source_advice",
            "advice",
            ["source_advice_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch_op.create_unique_constraint(
            "uq_user_notes_source_advice", ["user_id", "source_advice_id"]
        )
    op.create_index("ix_user_notes_source_advice_id", "user_notes", ["source_advice_id"])


def downgrade() -> None:
    op.drop_index("ix_user_notes_source_advice_id", table_name="user_notes")
    with op.batch_alter_table("user_notes") as batch_op:
        batch_op.drop_constraint("uq_user_notes_source_advice", type_="unique")
        batch_op.drop_constraint("fk_user_notes_source_advice", type_="foreignkey")
        batch_op.drop_column("source_advice_id")

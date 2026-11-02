"""advice, weekly plans and user notes

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-01
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
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
        batch_op.add_column(
            sa.Column("planning_consent_at", sa.DateTime(timezone=True), nullable=True)
        )

    op.create_table(
        "user_notes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content", sa.String(100), nullable=False),
        sa.Column("category", sa.String(16), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_user_notes_user_id", "user_notes", ["user_id"])
    op.create_index("ix_user_notes_user_created", "user_notes", ["user_id", "created_at"])

    op.create_table(
        "advice",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("for_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("context_json", sa.Text(), nullable=False),
        sa.Column("content_json", sa.Text(), nullable=True),
        sa.Column("observation_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("feedback", sa.String(24), nullable=True),
        sa.Column("feedback_reason", sa.String(500), nullable=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("prompt_version", sa.String(32), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_advice_user_id", "advice", ["user_id"])
    op.create_index("ix_advice_user_kind_date", "advice", ["user_id", "kind", "for_date"])
    op.create_index("ix_advice_user_created", "advice", ["user_id", "created_at"])

    if op.get_bind().dialect.name == "postgresql":
        _owner_policy("user_notes")
        _owner_policy("advice")


def downgrade() -> None:
    op.drop_index("ix_advice_user_created", table_name="advice")
    op.drop_index("ix_advice_user_kind_date", table_name="advice")
    op.drop_index("ix_advice_user_id", table_name="advice")
    op.drop_table("advice")
    op.drop_index("ix_user_notes_user_created", table_name="user_notes")
    op.drop_index("ix_user_notes_user_id", table_name="user_notes")
    op.drop_table("user_notes")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("planning_consent_at")

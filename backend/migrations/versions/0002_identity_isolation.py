"""account settings, audit events and PostgreSQL RLS

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-31
"""

import os
import re

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column("locale", sa.String(16), nullable=False, server_default="zh-CN")
        )

    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_audit_events_user_id", "audit_events", ["user_id"])
    op.create_index(
        "ix_audit_events_user_created", "audit_events", ["user_id", "created_at"]
    )

    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE audit_events ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE audit_events FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY audit_events_owner ON audit_events
            USING (
                user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
            )
            WITH CHECK (
                user_id = NULLIF(current_setting('app.current_user_id', true), '')::uuid
            )
            """
        )
        runtime_role = os.environ.get("POSTGRES_RUNTIME_ROLE")
        if runtime_role:
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", runtime_role) is None:
                raise ValueError("POSTGRES_RUNTIME_ROLE 不是合法的 PostgreSQL 角色名")
            quoted_role = op.get_bind().dialect.identifier_preparer.quote(runtime_role)
            op.execute(
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {quoted_role}"
            )
            op.execute(
                f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
                f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {quoted_role}"
            )


def downgrade() -> None:
    op.drop_index("ix_audit_events_user_created", table_name="audit_events")
    op.drop_index("ix_audit_events_user_id", table_name="audit_events")
    op.drop_table("audit_events")
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("locale")

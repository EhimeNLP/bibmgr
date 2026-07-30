"""Add passwordless email authentication and reference audit history.

Revision ID: 0002_email_authentication
Revises: 0001_reference_library
Create Date: 2026-07-27
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0002_email_authentication"
down_revision: str | None = "0001_reference_library"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="active",
            nullable=False,
        ),
        sa.Column(
            "first_verified_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "last_login_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active', 'disabled')",
            name="ck_users_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )

    op.create_table(
        "email_login_challenges",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("code_digest", sa.String(length=64), nullable=False),
        sa.Column("request_ip", sa.String(length=64), nullable=True),
        sa.Column(
            "attempts",
            sa.SmallInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "expires_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "consumed_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "attempts >= 0",
            name="ck_email_login_challenges_attempts",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_email_login_challenges_email_requested_at",
        "email_login_challenges",
        ["email", "requested_at"],
    )
    op.create_index(
        "ix_email_login_challenges_request_ip_requested_at",
        "email_login_challenges",
        ["request_ip", "requested_at"],
    )

    op.create_table(
        "user_sessions",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_digest", sa.String(length=64), nullable=False),
        sa.Column(
            "expires_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "revoked_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_digest"),
    )
    op.create_index(
        "ix_user_sessions_user_id",
        "user_sessions",
        ["user_id"],
    )
    op.create_index(
        "ix_user_sessions_expires_at",
        "user_sessions",
        ["expires_at"],
    )

    op.add_column(
        "bibliographic_references",
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "bibliographic_references",
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_bibliographic_references_created_by_user_id_users",
        "bibliographic_references",
        "users",
        ["created_by_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_bibliographic_references_updated_by_user_id_users",
        "bibliographic_references",
        "users",
        ["updated_by_user_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_bibliographic_references_created_by_user_id",
        "bibliographic_references",
        ["created_by_user_id"],
    )
    op.create_index(
        "ix_bibliographic_references_updated_by_user_id",
        "bibliographic_references",
        ["updated_by_user_id"],
    )

    op.create_table(
        "reference_audit_events",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("reference_id", sa.Uuid(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column(
            "before_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "after_data",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN ('create', 'update', 'delete')",
            name="ck_reference_audit_events_action",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_reference_audit_events_reference_occurred_at",
        "reference_audit_events",
        ["reference_id", "occurred_at"],
    )
    op.create_index(
        "ix_reference_audit_events_actor_occurred_at",
        "reference_audit_events",
        ["actor_user_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_reference_audit_events_actor_occurred_at",
        table_name="reference_audit_events",
    )
    op.drop_index(
        "ix_reference_audit_events_reference_occurred_at",
        table_name="reference_audit_events",
    )
    op.drop_table("reference_audit_events")

    op.drop_index(
        "ix_bibliographic_references_updated_by_user_id",
        table_name="bibliographic_references",
    )
    op.drop_index(
        "ix_bibliographic_references_created_by_user_id",
        table_name="bibliographic_references",
    )
    op.drop_constraint(
        "fk_bibliographic_references_updated_by_user_id_users",
        "bibliographic_references",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_bibliographic_references_created_by_user_id_users",
        "bibliographic_references",
        type_="foreignkey",
    )
    op.drop_column(
        "bibliographic_references", "updated_by_user_id"
    )
    op.drop_column(
        "bibliographic_references", "created_by_user_id"
    )

    op.drop_index(
        "ix_user_sessions_expires_at", table_name="user_sessions"
    )
    op.drop_index(
        "ix_user_sessions_user_id", table_name="user_sessions"
    )
    op.drop_table("user_sessions")

    op.drop_index(
        "ix_email_login_challenges_request_ip_requested_at",
        table_name="email_login_challenges",
    )
    op.drop_index(
        "ix_email_login_challenges_email_requested_at",
        table_name="email_login_challenges",
    )
    op.drop_table("email_login_challenges")
    op.drop_table("users")

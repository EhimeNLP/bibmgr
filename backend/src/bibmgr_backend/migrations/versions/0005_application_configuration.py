"""Store editable export profiles and venue mappings.

Revision ID: 0005_application_configuration
Revises: 0004_context_history
Create Date: 2026-07-29
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0005_application_configuration"
down_revision: str | None = "0004_context_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "application_configuration",
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column(
            "data",
            sa.JSON().with_variant(
                postgresql.JSONB(), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('export_profile', 'venue')",
            name="ck_application_configuration_kind",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_application_configuration_revision",
        ),
        sa.ForeignKeyConstraint(
            ["updated_by_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("kind", "key"),
    )
    op.create_index(
        "ix_application_configuration_updated_at",
        "application_configuration",
        ["updated_at"],
    )

    op.create_table(
        "application_configuration_audit_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "before_data",
            sa.JSON().with_variant(
                postgresql.JSONB(), "postgresql"
            ),
        ),
        sa.Column(
            "after_data",
            sa.JSON().with_variant(
                postgresql.JSONB(), "postgresql"
            ),
            nullable=False,
        ),
        sa.Column(
            "occurred_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('export_profile', 'venue')",
            name="ck_application_configuration_audit_kind",
        ),
        sa.CheckConstraint(
            "revision >= 1",
            name="ck_application_configuration_audit_revision",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "kind",
            "key",
            "revision",
            name="uq_application_configuration_audit_revision",
        ),
    )
    op.create_index(
        "ix_application_configuration_audit_occurred_at",
        "application_configuration_audit_events",
        ["occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_application_configuration_audit_occurred_at",
        table_name="application_configuration_audit_events",
    )
    op.drop_table("application_configuration_audit_events")
    op.drop_index(
        "ix_application_configuration_updated_at",
        table_name="application_configuration",
    )
    op.drop_table("application_configuration")

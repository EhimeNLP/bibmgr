"""Allow configuration deletion events in the audit log.

Revision ID: 0006_configuration_deletions
Revises: 0005_application_configuration
Create Date: 2026-07-30
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0006_configuration_deletions"
down_revision: str | None = "0005_application_configuration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "application_configuration_audit_events",
        "after_data",
        existing_type=postgresql.JSONB(),
        nullable=True,
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE application_configuration_audit_events "
            "SET after_data = before_data WHERE after_data IS NULL"
        )
    )
    op.alter_column(
        "application_configuration_audit_events",
        "after_data",
        existing_type=postgresql.JSONB(),
        nullable=False,
    )

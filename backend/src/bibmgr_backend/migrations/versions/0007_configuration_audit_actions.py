"""Record the action represented by each configuration audit event.

Revision ID: 0007_configuration_audit_actions
Revises: 0006_configuration_deletions
Create Date: 2026-07-30
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0007_configuration_audit_actions"
down_revision: str | None = "0006_configuration_deletions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "application_configuration_audit_events",
        sa.Column("action", sa.String(length=24), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE application_configuration_audit_events "
            "SET action = CASE "
            "WHEN after_data IS NULL THEN 'delete' "
            "ELSE 'change' END"
        )
    )
    op.alter_column(
        "application_configuration_audit_events",
        "action",
        existing_type=sa.String(length=24),
        nullable=False,
    )
    op.create_check_constraint(
        "ck_application_configuration_audit_action",
        "application_configuration_audit_events",
        "action IN ("
        "'change', 'create', 'override', 'update', "
        "'restore_default', 'delete'"
        ")",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_application_configuration_audit_action",
        "application_configuration_audit_events",
        type_="check",
    )
    op.drop_column(
        "application_configuration_audit_events",
        "action",
    )

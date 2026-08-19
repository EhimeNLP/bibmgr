"""Support citation-context revisions.

Revision ID: 0004_context_history
Revises: 0003_revertible_history
Create Date: 2026-07-28
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0004_context_history"
down_revision: str | None = "0003_revertible_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_reference_audit_events_action",
        "reference_audit_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_reference_audit_events_action",
        "reference_audit_events",
        (
            "action IN "
            "('baseline', 'create', 'update', 'delete', 'restore', 'context')"
        ),
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE reference_audit_events
        DISABLE TRIGGER reference_audit_events_append_only
        """
    )
    op.execute(
        """
        UPDATE reference_audit_events
        SET action = 'update'
        WHERE action = 'context'
        """
    )
    op.execute(
        """
        ALTER TABLE reference_audit_events
        ENABLE TRIGGER reference_audit_events_append_only
        """
    )
    op.drop_constraint(
        "ck_reference_audit_events_action",
        "reference_audit_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_reference_audit_events_action",
        "reference_audit_events",
        "action IN ('baseline', 'create', 'update', 'delete', 'restore')",
    )

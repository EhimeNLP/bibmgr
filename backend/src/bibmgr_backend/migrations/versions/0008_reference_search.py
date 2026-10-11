"""Track committed reference changes for disposable search indexes.

Revision ID: 0008_reference_search
Revises: 0007_configuration_audit_actions
Create Date: 2026-10-11
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0008_reference_search"
down_revision: str | None = "0007_configuration_audit_actions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    state = op.create_table(
        "reference_search_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("generation", sa.BigInteger(), nullable=False),
    )
    op.bulk_insert(state, [{"id": 1, "generation": 0}])
    op.create_table(
        "reference_search_changes",
        sa.Column("reference_id", sa.Uuid(), primary_key=True),
        sa.Column("generation", sa.BigInteger(), nullable=False),
    )
    op.create_index(
        "ix_reference_search_changes_generation",
        "reference_search_changes",
        ["generation"],
    )


def downgrade() -> None:
    op.drop_table("reference_search_changes")
    op.drop_table("reference_search_state")

"""Make reference history ordered and safely restorable.

Revision ID: 0003_revertible_history
Revises: 0002_email_authentication
Create Date: 2026-07-27
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0003_revertible_history"
down_revision: str | None = "0002_email_authentication"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "reference_history_heads",
        sa.Column("reference_id", sa.Uuid(), nullable=False),
        sa.Column(
            "latest_revision",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "latest_revision >= 0",
            name="ck_reference_history_heads_latest_revision",
        ),
        sa.PrimaryKeyConstraint("reference_id"),
    )
    op.create_index(
        "ix_reference_history_heads_updated_at",
        "reference_history_heads",
        ["updated_at"],
    )

    op.add_column(
        "reference_audit_events",
        sa.Column("revision", sa.Integer(), nullable=True),
    )
    op.add_column(
        "reference_audit_events",
        sa.Column(
            "restored_from_revision", sa.Integer(), nullable=True
        ),
    )
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                row_number() OVER (
                    PARTITION BY reference_id
                    ORDER BY occurred_at, id
                ) AS revision
            FROM reference_audit_events
        )
        UPDATE reference_audit_events AS event
        SET revision = ranked.revision
        FROM ranked
        WHERE event.id = ranked.id
        """
    )
    op.alter_column(
        "reference_audit_events",
        "revision",
        existing_type=sa.Integer(),
        nullable=False,
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
    op.create_check_constraint(
        "ck_reference_audit_events_revision",
        "reference_audit_events",
        "revision >= 1",
    )
    op.create_check_constraint(
        "ck_reference_audit_events_restored_from_revision",
        "reference_audit_events",
        (
            "restored_from_revision IS NULL "
            "OR restored_from_revision >= 1"
        ),
    )
    op.create_unique_constraint(
        "uq_reference_audit_events_revision",
        "reference_audit_events",
        ["reference_id", "revision"],
    )

    op.execute(
        """
        INSERT INTO reference_history_heads (
            reference_id,
            latest_revision,
            updated_at
        )
        SELECT
            reference_id,
            max(revision),
            max(occurred_at)
        FROM reference_audit_events
        GROUP BY reference_id
        """
    )
    op.execute(
        """
        INSERT INTO reference_history_heads (
            reference_id,
            latest_revision,
            updated_at
        )
        SELECT
            reference.id,
            0,
            reference.updated_at
        FROM bibliographic_references AS reference
        WHERE NOT EXISTS (
            SELECT 1
            FROM reference_history_heads AS history
            WHERE history.reference_id = reference.id
        )
        """
    )
    op.execute(
        """
        CREATE FUNCTION prevent_reference_audit_event_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                'reference_audit_events is append-only';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER reference_audit_events_append_only
        BEFORE UPDATE OR DELETE ON reference_audit_events
        FOR EACH ROW
        EXECUTE FUNCTION prevent_reference_audit_event_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TRIGGER reference_audit_events_append_only
        ON reference_audit_events
        """
    )
    op.execute(
        "DROP FUNCTION prevent_reference_audit_event_mutation()"
    )
    op.drop_constraint(
        "uq_reference_audit_events_revision",
        "reference_audit_events",
        type_="unique",
    )
    op.drop_constraint(
        "ck_reference_audit_events_restored_from_revision",
        "reference_audit_events",
        type_="check",
    )
    op.drop_constraint(
        "ck_reference_audit_events_revision",
        "reference_audit_events",
        type_="check",
    )
    op.drop_constraint(
        "ck_reference_audit_events_action",
        "reference_audit_events",
        type_="check",
    )
    op.execute(
        """
        UPDATE reference_audit_events
        SET action = CASE action
            WHEN 'baseline' THEN 'create'
            WHEN 'restore' THEN 'update'
            ELSE action
        END
        """
    )
    op.create_check_constraint(
        "ck_reference_audit_events_action",
        "reference_audit_events",
        "action IN ('create', 'update', 'delete')",
    )
    op.drop_column(
        "reference_audit_events", "restored_from_revision"
    )
    op.drop_column("reference_audit_events", "revision")

    op.drop_index(
        "ix_reference_history_heads_updated_at",
        table_name="reference_history_heads",
    )
    op.drop_table("reference_history_heads")

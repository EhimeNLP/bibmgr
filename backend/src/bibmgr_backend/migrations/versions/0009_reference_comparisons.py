"""Add a rebuildable, non-unique duplicate candidate index.

Existing records are indexed on the next reference write using the Rust engine.
No references are merged or removed by this migration.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0009_reference_comparisons"
down_revision = "0008_reference_search"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reference_comparisons",
        sa.Column("reference_id", sa.Uuid(), sa.ForeignKey("bibliographic_references.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("source_revision", sa.String(71), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("profile", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"), nullable=False),
    )
    op.create_table(
        "reference_comparison_keys",
        sa.Column("reference_id", sa.Uuid(), sa.ForeignKey("reference_comparisons.reference_id", ondelete="CASCADE"), primary_key=True),
        sa.Column("key", sa.String(64), primary_key=True),
    )
    op.create_index("ix_reference_comparison_keys_key", "reference_comparison_keys", ["key"])


def downgrade() -> None:
    op.drop_table("reference_comparison_keys")
    op.drop_table("reference_comparisons")

"""Persist search-only translations independently of the bibliography."""

from alembic import op
import sqlalchemy as sa

revision = "0010_search_translations"
down_revision = "0009_reference_comparisons"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "reference_search_translations",
        sa.Column(
            "reference_id",
            sa.Uuid(),
            sa.ForeignKey("bibliographic_references.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("source_revision", sa.String(71), nullable=False),
        sa.Column("provider", sa.String(255), nullable=False),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("model_revision", sa.String(255), nullable=False),
        sa.Column("translated_title", sa.Text(), nullable=False),
        sa.Column("translated_keywords", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("reference_search_translations")

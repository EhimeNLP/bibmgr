"""Create the bibliographic reference library.

Revision ID: 0001_reference_library
Revises:
Create Date: 2026-07-27
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0001_reference_library"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_table(
        "bibliographic_references",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("citation_key", sa.Text(), nullable=False),
        sa.Column("entry_type", sa.Text(), nullable=False),
        sa.Column("work_type", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("publication_year", sa.SmallInteger(), nullable=True),
        sa.Column("publication_date_raw", sa.Text(), nullable=True),
        sa.Column("venue_raw", sa.Text(), nullable=True),
        sa.Column("venue_id", sa.Text(), nullable=True),
        sa.Column("venue_name", sa.Text(), nullable=True),
        sa.Column("raw_bibtex", sa.Text(), nullable=False),
        sa.Column("source_revision", sa.String(length=71), nullable=False),
        sa.Column(
            "registration_source", sa.String(length=16), nullable=False
        ),
        sa.Column(
            "semantic_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False
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
            "registration_source IN ('manual', 'file', 'edit')",
            name="ck_bibliographic_references_registration_source",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_bibliographic_references_citation_key",
        "bibliographic_references",
        ["citation_key"],
    )
    op.create_index(
        "ix_bibliographic_references_publication_year",
        "bibliographic_references",
        ["publication_year"],
    )
    op.create_index(
        "ix_bibliographic_references_updated_at",
        "bibliographic_references",
        ["updated_at"],
    )
    op.create_index(
        "ix_bibliographic_references_title_trgm",
        "bibliographic_references",
        ["title"],
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_bibliographic_references_citation_key_trgm",
        "bibliographic_references",
        ["citation_key"],
        postgresql_using="gin",
        postgresql_ops={"citation_key": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_bibliographic_references_venue_raw_trgm",
        "bibliographic_references",
        ["venue_raw"],
        postgresql_using="gin",
        postgresql_ops={"venue_raw": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_bibliographic_references_semantic_data",
        "bibliographic_references",
        ["semantic_data"],
        postgresql_using="gin",
        postgresql_ops={"semantic_data": "jsonb_path_ops"},
    )

    op.create_table(
        "reference_contributors",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reference_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column(
            "given_names", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "family_names", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "name_prefixes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "name_suffixes",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("literal_name", sa.Text(), nullable=True),
        sa.Column(
            "semantic_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.CheckConstraint(
            "role IN ('author', 'editor')",
            name="ck_reference_contributors_role",
        ),
        sa.ForeignKeyConstraint(
            ["reference_id"],
            ["bibliographic_references.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "reference_id",
            "role",
            "position",
            name="uq_reference_contributors_position",
        ),
    )
    op.create_index(
        "ix_reference_contributors_display_name_trgm",
        "reference_contributors",
        ["display_name"],
        postgresql_using="gin",
        postgresql_ops={"display_name": "gin_trgm_ops"},
    )

    op.create_table(
        "reference_identifiers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reference_id", sa.Uuid(), nullable=False),
        sa.Column("scheme", sa.String(length=32), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("normalized_value", sa.Text(), nullable=False),
        sa.Column(
            "semantic_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["reference_id"],
            ["bibliographic_references.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "reference_id",
            "scheme",
            "normalized_value",
            name="uq_reference_identifiers_per_reference",
        ),
    )
    op.create_index(
        "uq_reference_identifiers_strong_identity",
        "reference_identifiers",
        ["scheme", "normalized_value"],
        unique=True,
        postgresql_where=sa.text("scheme IN ('doi', 'arxiv')"),
    )
    op.create_index(
        "ix_reference_identifiers_normalized_value",
        "reference_identifiers",
        ["normalized_value"],
    )
    op.create_index(
        "ix_reference_identifiers_value_trgm",
        "reference_identifiers",
        ["normalized_value"],
        postgresql_using="gin",
        postgresql_ops={"normalized_value": "gin_trgm_ops"},
    )

    op.create_table(
        "reference_urls",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reference_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column(
            "semantic_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["reference_id"],
            ["bibliographic_references.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "reference_id", "position", name="uq_reference_urls_position"
        ),
    )

    op.create_table(
        "citation_contexts",
        sa.Column(
            "id",
            sa.Uuid(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("reference_id", sa.Uuid(), nullable=False),
        sa.Column("source_paper_title", sa.Text(), nullable=True),
        sa.Column("source_file_name", sa.Text(), nullable=True),
        sa.Column("before_text", sa.Text(), nullable=True),
        sa.Column("context_text", sa.Text(), nullable=False),
        sa.Column("after_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["reference_id"],
            ["bibliographic_references.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("citation_contexts")
    op.drop_table("reference_urls")
    op.drop_index(
        "ix_reference_identifiers_value_trgm",
        table_name="reference_identifiers",
    )
    op.drop_index(
        "ix_reference_identifiers_normalized_value",
        table_name="reference_identifiers",
    )
    op.drop_index(
        "uq_reference_identifiers_strong_identity",
        table_name="reference_identifiers",
    )
    op.drop_table("reference_identifiers")
    op.drop_index(
        "ix_reference_contributors_display_name_trgm",
        table_name="reference_contributors",
    )
    op.drop_table("reference_contributors")
    op.drop_index(
        "ix_bibliographic_references_semantic_data",
        table_name="bibliographic_references",
    )
    op.drop_index(
        "ix_bibliographic_references_venue_raw_trgm",
        table_name="bibliographic_references",
    )
    op.drop_index(
        "ix_bibliographic_references_citation_key_trgm",
        table_name="bibliographic_references",
    )
    op.drop_index(
        "ix_bibliographic_references_title_trgm",
        table_name="bibliographic_references",
    )
    op.drop_index(
        "ix_bibliographic_references_updated_at",
        table_name="bibliographic_references",
    )
    op.drop_index(
        "ix_bibliographic_references_publication_year",
        table_name="bibliographic_references",
    )
    op.drop_index(
        "ix_bibliographic_references_citation_key",
        table_name="bibliographic_references",
    )
    op.drop_table("bibliographic_references")

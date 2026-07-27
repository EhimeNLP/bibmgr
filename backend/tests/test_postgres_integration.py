from __future__ import annotations

import os
import uuid

from alembic import command
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from bibmgr_backend.migrate import migration_config


POSTGRES_URL = os.environ.get("BIBMGR_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="BIBMGR_TEST_POSTGRES_URL is not configured",
)


def test_postgresql_migrations_indexes_and_append_only_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert POSTGRES_URL is not None
    monkeypatch.setenv("BIBMGR_DATABASE_URL", POSTGRES_URL)
    config = migration_config()
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    command.check(config)

    engine = create_engine(POSTGRES_URL)
    user_id = uuid.uuid4()
    first_reference_id = uuid.uuid4()
    second_reference_id = uuid.uuid4()
    event_id = uuid.uuid4()
    with engine.begin() as connection:
        extensions = set(
            connection.scalars(
                text(
                    "SELECT extname FROM pg_extension "
                    "WHERE extname = 'pg_trgm'"
                )
            )
        )
        assert extensions == {"pg_trgm"}
        index_names = set(
            connection.scalars(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname = current_schema()"
                )
            )
        )
        assert "ix_bibliographic_references_title_trgm" in index_names
        assert "uq_reference_identifiers_strong_identity" in index_names

        connection.execute(
            text(
                "INSERT INTO users (id, email, status) "
                "VALUES (:id, :email, 'active')"
            ),
            {"id": user_id, "email": "postgres-test@ai.cs.ehime-u.ac.jp"},
        )
        for reference_id, key, source in (
            (first_reference_id, "first", "pipeline"),
            (second_reference_id, "second", "manual"),
        ):
            connection.execute(
                text(
                    """
                    INSERT INTO bibliographic_references (
                        id, citation_key, entry_type, work_type, title,
                        raw_bibtex, source_revision, registration_source,
                        semantic_data, created_by_user_id, updated_by_user_id
                    ) VALUES (
                        :id, :key, 'article', 'journal_article', :key,
                        :bibtex, :revision, :source, '{}'::jsonb, :user, :user
                    )
                    """
                ),
                {
                    "id": reference_id,
                    "key": key,
                    "bibtex": f"@article{{{key}}}",
                    "revision": f"sha256:{key:0<64}"[:71],
                    "source": source,
                    "user": user_id,
                },
            )
        connection.execute(
            text(
                """
                INSERT INTO reference_identifiers (
                    reference_id, scheme, position, value,
                    normalized_value, semantic_data
                ) VALUES (
                    :reference, 'doi', 0, '10.1000/integration',
                    '10.1000/integration', '{}'::jsonb
                )
                """
            ),
            {"reference": first_reference_id},
        )
        connection.execute(
            text(
                "INSERT INTO reference_history_heads "
                "(reference_id, latest_revision) VALUES (:reference, 1)"
            ),
            {"reference": first_reference_id},
        )
        connection.execute(
            text(
                """
                INSERT INTO reference_audit_events (
                    id, reference_id, actor_user_id, revision, action,
                    before_data, after_data
                ) VALUES (
                    :id, :reference, :user, 1, 'context',
                    NULL, '{}'::jsonb
                )
                """
            ),
            {
                "id": event_id,
                "reference": first_reference_id,
                "user": user_id,
            },
        )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO reference_identifiers (
                    reference_id, scheme, position, value,
                    normalized_value, semantic_data
                ) VALUES (
                    :reference, 'doi', 0, '10.1000/integration',
                    '10.1000/integration', '{}'::jsonb
                )
                """
            ),
            {"reference": second_reference_id},
        )

    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE reference_audit_events "
                "SET action = 'update' WHERE id = :id"
            ),
            {"id": event_id},
        )

    command.downgrade(config, "base")
    command.upgrade(config, "head")

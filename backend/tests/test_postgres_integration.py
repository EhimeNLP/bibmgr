from __future__ import annotations

from concurrent.futures import (
    ThreadPoolExecutor,
    TimeoutError as FutureTimeoutError,
)
import os
from threading import Event
import uuid

from alembic import command
import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from bibmgr_backend.auth import (
    AuthenticationManager,
    AuthenticationRateLimitError,
)
from bibmgr_backend.db_models import EmailLoginChallenge
from bibmgr_backend.migrate import migration_config


POSTGRES_URL = os.environ.get("BIBMGR_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="BIBMGR_TEST_POSTGRES_URL is not configured",
)


class UnusedMailer:
    def send_login_code(
        self,
        *,
        recipient: str,
        code: str,
        expires_in_minutes: int,
    ) -> None:
        raise AssertionError("reservation must not send email")


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
            (first_reference_id, "first", "file"),
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


def test_login_request_reservations_are_serialized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert POSTGRES_URL is not None
    monkeypatch.setenv("BIBMGR_DATABASE_URL", POSTGRES_URL)
    config = migration_config()
    command.downgrade(config, "base")
    command.upgrade(config, "head")

    engine = create_engine(POSTGRES_URL)
    sessions = sessionmaker(
        bind=engine,
        class_=Session,
        expire_on_commit=False,
    )
    authentication = AuthenticationManager(
        mailer=UnusedMailer(),
        secret=b"postgres-authentication-test-secret",
        code_generator=lambda: "12345678",
        secure_cookie=False,
    )
    email = "concurrent@ai.cs.ehime-u.ac.jp"
    request_ip = "192.0.2.10"
    second_started = Event()

    def reserve_second_request() -> str:
        second_started.set()
        with sessions() as session:
            try:
                authentication.reserve_login_code(
                    session,
                    email=email,
                    request_ip=request_ip,
                )
                session.commit()
                return "reserved"
            except AuthenticationRateLimitError:
                session.rollback()
                return "limited"

    with sessions() as first_session:
        first_delivery = authentication.reserve_login_code(
            first_session,
            email=email,
            request_ip=request_ip,
        )
        assert first_delivery is not None

        with ThreadPoolExecutor(max_workers=1) as executor:
            second = executor.submit(reserve_second_request)
            assert second_started.wait(timeout=2)
            try:
                with pytest.raises(FutureTimeoutError):
                    second.result(timeout=0.2)
            finally:
                first_session.commit()
            assert second.result(timeout=5) == "limited"

    with sessions() as session:
        assert session.scalar(
            select(func.count()).select_from(EmailLoginChallenge)
        ) == 1

from collections.abc import Iterator
from copy import deepcopy
from typing import Any
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from bibmgr_backend.configuration import (
    EXPORT_PROFILE,
    VENUE,
    ApplicationConfiguration,
    _is_configuration_write_conflict,
    _locked_configuration_statement,
)
from bibmgr_backend.db_models import (
    ApplicationConfigurationAuditEvent,
    ApplicationConfigurationRecord,
    Base,
    UserRecord,
)


BUILTIN_PROFILE = {
    "schema_version": "1",
    "profile": "builtin-profile",
    "display_name": "Built-in Profile",
    "description": "Default profile description.",
}
BUILTIN_VENUE = {
    "id": "builtin-venue",
    "full_name": "Built-in Conference on Artificial Intelligence",
    "short_name": "BCAI",
    "aliases": ["Built-in AI Conference"],
    "kind": "conference",
}


class ConfigurationEngineStub:
    def builtin_configuration(self) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "export_profiles": [deepcopy(BUILTIN_PROFILE)],
            "venue_registry": {
                "schema_version": "1",
                "venues": [deepcopy(BUILTIN_VENUE)],
            },
        }

    def validate_export_profile(
        self, profile_data: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "profile": deepcopy(profile_data),
        }

    def validate_venue_registry(
        self, venue_registry: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "venue_registry": deepcopy(venue_registry),
        }


@pytest.fixture
def configuration_context() -> Iterator[
    tuple[ApplicationConfiguration, Session, uuid.UUID]
]:
    database = create_engine("sqlite+pysqlite://")
    Base.metadata.create_all(database)
    session = Session(database, expire_on_commit=False)
    actor = UserRecord(email="configuration-test@example.test")
    session.add(actor)
    session.flush()
    yield ApplicationConfiguration(ConfigurationEngineStub()), session, actor.id
    session.close()


def test_configuration_lock_targets_only_the_override_record() -> None:
    statement = _locked_configuration_statement(EXPORT_PROFILE, "laboratory")
    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "LEFT OUTER JOIN users" in sql
    assert sql.endswith("FOR UPDATE OF application_configuration")


@pytest.mark.parametrize(
    "constraint_name",
    [
        "application_configuration_pkey",
        "uq_application_configuration_audit_revision",
    ],
)
def test_configuration_constraint_conflicts_are_recognized(
    constraint_name: str,
) -> None:
    class Diagnostic:
        pass

    class DatabaseError:
        diag = Diagnostic()

    DatabaseError.diag.constraint_name = constraint_name
    error = IntegrityError("INSERT", {}, DatabaseError())

    assert _is_configuration_write_conflict(error)


def test_unrelated_integrity_error_is_not_a_configuration_conflict() -> None:
    class Diagnostic:
        constraint_name = "fk_application_configuration_user"

    class DatabaseError:
        diag = Diagnostic()

    error = IntegrityError("INSERT", {}, DatabaseError())

    assert not _is_configuration_write_conflict(error)


@pytest.mark.parametrize(
    ("kind", "key", "changed_field", "changed_value"),
    [
        (
            EXPORT_PROFILE,
            "builtin-profile",
            "description",
            "Changed profile description.",
        ),
        (
            VENUE,
            "builtin-venue",
            "short_name",
            "BCAI 2026",
        ),
    ],
)
def test_first_builtin_change_records_only_the_real_override(
    configuration_context: tuple[
        ApplicationConfiguration, Session, uuid.UUID
    ],
    kind: str,
    key: str,
    changed_field: str,
    changed_value: str,
) -> None:
    configuration, session, actor_id = configuration_context
    before = _builtin_data(kind)
    after = {**before, changed_field: changed_value}

    _save(
        configuration,
        session,
        kind=kind,
        key=key,
        data=after,
        expected_revision=0,
        actor_id=actor_id,
    )

    event = _events(session, kind, key)[0]
    assert event.action == "override"
    assert event.before_data == before
    assert event.after_data == after
    assert _changed_top_level_fields(
        event.before_data, event.after_data
    ) == {changed_field}


@pytest.mark.parametrize(
    ("kind", "key"),
    [
        (EXPORT_PROFILE, "builtin-profile"),
        (VENUE, "builtin-venue"),
    ],
)
def test_unchanged_builtin_is_a_complete_noop(
    configuration_context: tuple[
        ApplicationConfiguration, Session, uuid.UUID
    ],
    kind: str,
    key: str,
) -> None:
    configuration, session, actor_id = configuration_context
    reordered_builtin = dict(reversed(_builtin_data(kind).items()))

    entry = _save(
        configuration,
        session,
        kind=kind,
        key=key,
        data=reordered_builtin,
        expected_revision=0,
        actor_id=actor_id,
    )

    assert entry["revision"] == 0
    assert _events(session, kind, key) == []
    assert session.get(ApplicationConfigurationRecord, (kind, key)) is None


@pytest.mark.parametrize("kind", [EXPORT_PROFILE, VENUE])
def test_builtin_history_has_exact_snapshots_for_every_transition(
    configuration_context: tuple[
        ApplicationConfiguration, Session, uuid.UUID
    ],
    kind: str,
) -> None:
    configuration, session, actor_id = configuration_context
    key = "builtin-profile" if kind == EXPORT_PROFILE else "builtin-venue"
    original = _builtin_data(kind)
    first = {
        **original,
        _change_field(kind): "First changed value.",
    }
    second = {
        **first,
        _change_field(kind): "Second changed value.",
    }

    _save(
        configuration,
        session,
        kind=kind,
        key=key,
        data=first,
        expected_revision=0,
        actor_id=actor_id,
    )
    unchanged = _save(
        configuration,
        session,
        kind=kind,
        key=key,
        data=first,
        expected_revision=1,
        actor_id=actor_id,
    )
    _save(
        configuration,
        session,
        kind=kind,
        key=key,
        data=second,
        expected_revision=1,
        actor_id=actor_id,
    )
    _delete(
        configuration,
        session,
        kind=kind,
        key=key,
        expected_revision=2,
        actor_id=actor_id,
    )

    assert unchanged["revision"] == 1
    events = _events(session, kind, key)
    assert [
        (event.revision, event.action) for event in events
    ] == [
        (1, "override"),
        (2, "update"),
        (3, "restore_default"),
    ]
    assert [
        (event.before_data, event.after_data) for event in events
    ] == [
        (original, first),
        (first, second),
        (second, original),
    ]


@pytest.mark.parametrize("kind", [EXPORT_PROFILE, VENUE])
def test_custom_history_distinguishes_create_update_delete_and_recreate(
    configuration_context: tuple[
        ApplicationConfiguration, Session, uuid.UUID
    ],
    kind: str,
) -> None:
    configuration, session, actor_id = configuration_context
    key = "custom-profile" if kind == EXPORT_PROFILE else "custom-venue"
    first = _custom_data(kind, key, "First custom value.")
    second = _custom_data(kind, key, "Second custom value.")

    _save(
        configuration,
        session,
        kind=kind,
        key=key,
        data=first,
        expected_revision=0,
        actor_id=actor_id,
    )
    _save(
        configuration,
        session,
        kind=kind,
        key=key,
        data=second,
        expected_revision=1,
        actor_id=actor_id,
    )
    _delete(
        configuration,
        session,
        kind=kind,
        key=key,
        expected_revision=2,
        actor_id=actor_id,
    )
    _save(
        configuration,
        session,
        kind=kind,
        key=key,
        data=first,
        expected_revision=0,
        actor_id=actor_id,
    )

    events = _events(session, kind, key)
    assert [
        (event.revision, event.action) for event in events
    ] == [
        (1, "create"),
        (2, "update"),
        (3, "delete"),
        (4, "create"),
    ]
    assert [
        (event.before_data, event.after_data) for event in events
    ] == [
        (None, first),
        (first, second),
        (second, None),
        (None, first),
    ]


def _save(
    configuration: ApplicationConfiguration,
    session: Session,
    *,
    kind: str,
    key: str,
    data: dict[str, Any],
    expected_revision: int,
    actor_id: uuid.UUID,
) -> dict[str, Any]:
    if kind == EXPORT_PROFILE:
        return configuration.save_export_profile(
            session,
            profile_id=key,
            profile_data=data,
            expected_revision=expected_revision,
            actor_user_id=actor_id,
        )
    return configuration.save_venue(
        session,
        venue_id=key,
        venue_data=data,
        expected_revision=expected_revision,
        actor_user_id=actor_id,
    )


def _delete(
    configuration: ApplicationConfiguration,
    session: Session,
    *,
    kind: str,
    key: str,
    expected_revision: int,
    actor_id: uuid.UUID,
) -> dict[str, Any]:
    if kind == EXPORT_PROFILE:
        return configuration.delete_export_profile(
            session,
            profile_id=key,
            expected_revision=expected_revision,
            actor_user_id=actor_id,
        )
    return configuration.delete_venue(
        session,
        venue_id=key,
        expected_revision=expected_revision,
        actor_user_id=actor_id,
    )


def _events(
    session: Session, kind: str, key: str
) -> list[ApplicationConfigurationAuditEvent]:
    return list(
        session.scalars(
            select(ApplicationConfigurationAuditEvent)
            .where(
                ApplicationConfigurationAuditEvent.kind == kind,
                ApplicationConfigurationAuditEvent.key == key,
            )
            .order_by(ApplicationConfigurationAuditEvent.revision)
        )
    )


def _builtin_data(kind: str) -> dict[str, Any]:
    return deepcopy(
        BUILTIN_PROFILE if kind == EXPORT_PROFILE else BUILTIN_VENUE
    )


def _change_field(kind: str) -> str:
    return "description" if kind == EXPORT_PROFILE else "full_name"


def _custom_data(
    kind: str, key: str, changed_value: str
) -> dict[str, Any]:
    if kind == EXPORT_PROFILE:
        return {
            **BUILTIN_PROFILE,
            "profile": key,
            "display_name": changed_value,
        }
    return {
        **BUILTIN_VENUE,
        "id": key,
        "full_name": changed_value,
    }


def _changed_top_level_fields(
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> set[str]:
    before_values = before or {}
    after_values = after or {}
    return {
        key
        for key in before_values.keys() | after_values.keys()
        if before_values.get(key) != after_values.get(key)
    }

"""Versioned, auditable application configuration backed by database overrides."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Protocol
import re
import uuid

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from .db_models import (
    ApplicationConfigurationAuditEvent,
    ApplicationConfigurationRecord,
    utc_now,
)
from .library import LibraryError


EXPORT_PROFILE = "export_profile"
VENUE = "venue"
_CONFIGURATION_KEY = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _locked_configuration_statement(
    kind: str, key: str
) -> Select[tuple[ApplicationConfigurationRecord]]:
    return (
        select(ApplicationConfigurationRecord)
        .where(
            ApplicationConfigurationRecord.kind == kind,
            ApplicationConfigurationRecord.key == key,
        )
        .with_for_update(of=ApplicationConfigurationRecord)
    )


class ConfigurationEngine(Protocol):
    def builtin_configuration(self) -> dict[str, Any]: ...

    def validate_export_profile(
        self, profile_data: dict[str, Any]
    ) -> dict[str, Any]: ...

    def validate_venue_registry(
        self, venue_registry: dict[str, Any]
    ) -> dict[str, Any]: ...


class ConfigurationNotFoundError(LibraryError):
    code = "configuration_not_found"
    status_code = 404


class StaleConfigurationError(LibraryError):
    code = "stale_configuration"
    status_code = 409


class InvalidConfigurationError(LibraryError):
    code = "invalid_configuration"
    status_code = 422


class ApplicationConfiguration:
    def __init__(self, engine: ConfigurationEngine) -> None:
        self.engine = engine

    def catalog(self, session: Session) -> dict[str, Any]:
        builtins = self._builtins()
        records = list(
            session.scalars(
                select(ApplicationConfigurationRecord).order_by(
                    ApplicationConfigurationRecord.kind,
                    ApplicationConfigurationRecord.key,
                )
            )
        )
        overrides = {(record.kind, record.key): record for record in records}

        profiles: list[dict[str, Any]] = []
        seen_profiles: set[str] = set()
        for profile in builtins["export_profiles"]:
            key = _profile_id(profile)
            seen_profiles.add(key)
            record = overrides.get((EXPORT_PROFILE, key))
            profiles.append(
                self._entry(
                    key=key,
                    data=record.data if record else profile,
                    record=record,
                    built_in=True,
                )
            )
        for record in records:
            if record.kind != EXPORT_PROFILE or record.key in seen_profiles:
                continue
            profiles.append(
                self._entry(
                    key=record.key,
                    data=record.data,
                    record=record,
                    built_in=False,
                )
            )

        venues: list[dict[str, Any]] = []
        seen_venues: set[str] = set()
        for venue in builtins["venue_registry"]["venues"]:
            key = _venue_id(venue)
            seen_venues.add(key)
            record = overrides.get((VENUE, key))
            venues.append(
                self._entry(
                    key=key,
                    data=record.data if record else venue,
                    record=record,
                    built_in=True,
                )
            )
        for record in records:
            if record.kind != VENUE or record.key in seen_venues:
                continue
            venues.append(
                self._entry(
                    key=record.key,
                    data=record.data,
                    record=record,
                    built_in=False,
                )
            )
        venues.sort(key=lambda item: (item["data"]["kind"], item["key"]))

        return {
            "schema_version": "1",
            "export_profiles": profiles,
            "venues": venues,
        }

    def export_profile_catalog(self, session: Session) -> dict[str, Any]:
        catalog = self.catalog(session)
        return {
            "schema_version": "1",
            "profiles": [
                {
                    "id": entry["key"],
                    "display_name": entry["data"]["display_name"],
                    "description": entry["data"]["description"],
                    "validation_profile": entry["data"][
                        "validation_profile"
                    ],
                    "preprint_representation": entry["data"][
                        "preprint_representation"
                    ],
                }
                for entry in catalog["export_profiles"]
            ],
        }

    def export_profile(
        self, session: Session, profile_id: str
    ) -> dict[str, Any]:
        for entry in self.catalog(session)["export_profiles"]:
            if entry["key"] == profile_id:
                return deepcopy(entry["data"])
        raise ConfigurationNotFoundError(
            f"Unknown export profile `{profile_id}`."
        )

    def venue_registry(self, session: Session) -> dict[str, Any]:
        return {
            "schema_version": "1",
            "venues": [
                deepcopy(entry["data"])
                for entry in self.catalog(session)["venues"]
            ],
        }

    def history(
        self,
        session: Session,
        *,
        kind: str,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        if kind not in {EXPORT_PROFILE, VENUE}:
            raise InvalidConfigurationError(
                f"Unknown configuration kind `{kind}`."
            )
        predicate = ApplicationConfigurationAuditEvent.kind == kind
        total = int(
            session.scalar(
                select(func.count())
                .select_from(ApplicationConfigurationAuditEvent)
                .where(predicate)
            )
            or 0
        )
        events = list(
            session.scalars(
                select(ApplicationConfigurationAuditEvent)
                .where(predicate)
                .order_by(
                    ApplicationConfigurationAuditEvent.occurred_at.desc(),
                    ApplicationConfigurationAuditEvent.key.asc(),
                    ApplicationConfigurationAuditEvent.revision.desc(),
                )
                .limit(limit)
                .offset(offset)
            )
        )
        return {
            "schema_version": "1",
            "kind": kind,
            "items": [
                {
                    "id": str(event.id),
                    "key": event.key,
                    "revision": event.revision,
                    "action": event.action,
                    "before_data": deepcopy(event.before_data),
                    "after_data": deepcopy(event.after_data),
                    "occurred_at": event.occurred_at.isoformat(),
                    "actor": {
                        "id": str(event.actor.id),
                        "email": event.actor.email,
                    },
                }
                for event in events
            ],
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    def save_export_profile(
        self,
        session: Session,
        *,
        profile_id: str,
        profile_data: dict[str, Any],
        expected_revision: int,
        actor_user_id: uuid.UUID,
    ) -> dict[str, Any]:
        self._validate_key(profile_id)
        candidate = deepcopy(profile_data)
        if candidate.get("profile") != profile_id:
            raise InvalidConfigurationError(
                "The profile field must match the URL profile ID."
            )
        validated = self.engine.validate_export_profile(candidate)
        canonical = validated.get("profile")
        if not isinstance(canonical, dict):
            raise InvalidConfigurationError(
                "The native engine returned an invalid export profile."
            )
        record = self._save(
            session,
            kind=EXPORT_PROFILE,
            key=profile_id,
            data=canonical,
            expected_revision=expected_revision,
            actor_user_id=actor_user_id,
        )
        return self._entry(
            key=profile_id,
            data=record.data if record else canonical,
            record=record,
            built_in=self._is_builtin(EXPORT_PROFILE, profile_id),
        )

    def save_venue(
        self,
        session: Session,
        *,
        venue_id: str,
        venue_data: dict[str, Any],
        expected_revision: int,
        actor_user_id: uuid.UUID,
    ) -> dict[str, Any]:
        self._validate_key(venue_id)
        candidate = deepcopy(venue_data)
        if candidate.get("id") != venue_id:
            raise InvalidConfigurationError(
                "The venue id must match the URL venue ID."
            )
        effective = self.venue_registry(session)
        venues = effective["venues"]
        replaced = False
        for index, venue in enumerate(venues):
            if venue.get("id") == venue_id:
                venues[index] = candidate
                replaced = True
                break
        if not replaced:
            venues.append(candidate)
        validated = self.engine.validate_venue_registry(effective)
        registry = validated.get("venue_registry")
        if not isinstance(registry, dict):
            raise InvalidConfigurationError(
                "The native engine returned an invalid venue registry."
            )
        canonical = next(
            (
                venue
                for venue in registry.get("venues", [])
                if isinstance(venue, dict) and venue.get("id") == venue_id
            ),
            None,
        )
        if canonical is None:
            raise InvalidConfigurationError(
                "The validated venue registry omitted the requested venue."
            )
        record = self._save(
            session,
            kind=VENUE,
            key=venue_id,
            data=canonical,
            expected_revision=expected_revision,
            actor_user_id=actor_user_id,
        )
        return self._entry(
            key=venue_id,
            data=record.data if record else canonical,
            record=record,
            built_in=self._is_builtin(VENUE, venue_id),
        )

    def delete_export_profile(
        self,
        session: Session,
        *,
        profile_id: str,
        expected_revision: int,
        actor_user_id: uuid.UUID,
    ) -> dict[str, Any]:
        return self._delete(
            session,
            kind=EXPORT_PROFILE,
            key=profile_id,
            expected_revision=expected_revision,
            actor_user_id=actor_user_id,
        )

    def delete_venue(
        self,
        session: Session,
        *,
        venue_id: str,
        expected_revision: int,
        actor_user_id: uuid.UUID,
    ) -> dict[str, Any]:
        return self._delete(
            session,
            kind=VENUE,
            key=venue_id,
            expected_revision=expected_revision,
            actor_user_id=actor_user_id,
        )

    def _save(
        self,
        session: Session,
        *,
        kind: str,
        key: str,
        data: dict[str, Any],
        expected_revision: int,
        actor_user_id: uuid.UUID,
    ) -> ApplicationConfigurationRecord | None:
        record = session.scalar(
            _locked_configuration_statement(kind, key)
        )
        visible_revision = record.revision if record else 0
        if visible_revision != expected_revision:
            raise StaleConfigurationError(
                "The setting changed after it was loaded.",
                details={"revision": visible_revision},
            )
        if record is not None and record.data == data:
            return record
        built_in_data = (
            self._builtin_data(kind, key) if record is None else None
        )
        if record is None and built_in_data == data:
            return None
        action = (
            "update"
            if record is not None
            else "override"
            if built_in_data is not None
            else "create"
        )
        before_data = deepcopy(
            record.data if record is not None else built_in_data
        )
        timestamp = utc_now()
        revision = (
            record.revision + 1
            if record
            else self._last_audit_revision(session, kind, key) + 1
        )
        if record is None:
            record = ApplicationConfigurationRecord(
                kind=kind,
                key=key,
                data=deepcopy(data),
                revision=revision,
                updated_by_user_id=actor_user_id,
                created_at=timestamp,
                updated_at=timestamp,
            )
            session.add(record)
        else:
            record.data = deepcopy(data)
            record.revision = revision
            record.updated_by_user_id = actor_user_id
            record.updated_at = timestamp
        session.add(
            ApplicationConfigurationAuditEvent(
                kind=kind,
                key=key,
                revision=revision,
                action=action,
                actor_user_id=actor_user_id,
                before_data=before_data,
                after_data=deepcopy(data),
                occurred_at=timestamp,
            )
        )
        session.flush()
        return record

    def _delete(
        self,
        session: Session,
        *,
        kind: str,
        key: str,
        expected_revision: int,
        actor_user_id: uuid.UUID,
    ) -> dict[str, Any]:
        record = session.scalar(
            _locked_configuration_statement(kind, key)
        )
        if record is None:
            raise ConfigurationNotFoundError(
                f"No editable configuration exists for `{key}`."
            )
        if record.revision != expected_revision:
            raise StaleConfigurationError(
                "The setting changed after it was loaded.",
                details={"revision": record.revision},
            )

        built_in_data = self._builtin_data(kind, key)
        revision = record.revision + 1
        session.add(
            ApplicationConfigurationAuditEvent(
                kind=kind,
                key=key,
                revision=revision,
                action=(
                    "restore_default"
                    if built_in_data is not None
                    else "delete"
                ),
                actor_user_id=actor_user_id,
                before_data=deepcopy(record.data),
                after_data=deepcopy(built_in_data),
                occurred_at=utc_now(),
            )
        )
        session.delete(record)
        session.flush()
        return {
            "key": key,
            "revision": revision,
            "reset": built_in_data is not None,
        }

    def _builtins(self) -> dict[str, Any]:
        result = self.engine.builtin_configuration()
        if (
            not isinstance(result.get("export_profiles"), list)
            or not isinstance(result.get("venue_registry"), dict)
            or not isinstance(
                result["venue_registry"].get("venues"), list
            )
        ):
            raise InvalidConfigurationError(
                "The native built-in configuration is incomplete."
            )
        return result

    def _is_builtin(self, kind: str, key: str) -> bool:
        return self._builtin_data(kind, key) is not None

    def _builtin_data(
        self, kind: str, key: str
    ) -> dict[str, Any] | None:
        builtins = self._builtins()
        if kind == EXPORT_PROFILE:
            return next(
                (
                    deepcopy(profile)
                    for profile in builtins["export_profiles"]
                    if _profile_id(profile) == key
                ),
                None,
            )
        return next(
            (
                deepcopy(venue)
                for venue in builtins["venue_registry"]["venues"]
                if _venue_id(venue) == key
            ),
            None,
        )

    @staticmethod
    def _last_audit_revision(
        session: Session, kind: str, key: str
    ) -> int:
        revision = session.scalar(
            select(func.max(ApplicationConfigurationAuditEvent.revision)).where(
                ApplicationConfigurationAuditEvent.kind == kind,
                ApplicationConfigurationAuditEvent.key == key,
            )
        )
        return int(revision or 0)

    @staticmethod
    def _entry(
        *,
        key: str,
        data: dict[str, Any],
        record: ApplicationConfigurationRecord | None,
        built_in: bool,
    ) -> dict[str, Any]:
        return {
            "key": key,
            "data": deepcopy(data),
            "revision": record.revision if record else 0,
            "built_in": built_in,
            "updated_at": (
                record.updated_at.isoformat() if record else None
            ),
            "updated_by": (
                {
                    "id": str(record.updated_by.id),
                    "email": record.updated_by.email,
                }
                if record
                else None
            ),
        }

    @staticmethod
    def _validate_key(value: str) -> None:
        if not _CONFIGURATION_KEY.fullmatch(value):
            raise InvalidConfigurationError(
                "Configuration IDs must use lowercase kebab-case."
            )


def _profile_id(profile: dict[str, Any]) -> str:
    value = profile.get("profile")
    if not isinstance(value, str) or not value:
        raise InvalidConfigurationError(
            "A built-in export profile has no profile ID."
        )
    return value


def _venue_id(venue: dict[str, Any]) -> str:
    value = venue.get("id")
    if not isinstance(value, str) or not value:
        raise InvalidConfigurationError(
            "A built-in venue has no venue ID."
        )
    return value

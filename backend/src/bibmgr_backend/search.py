"""Synchronize committed PostgreSQL records into a process-local Tantivy index."""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any
import uuid

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .db_models import (
    ReferenceRecord,
    ReferenceSearchChange,
    ReferenceSearchState,
    UserRecord,
)
from .native import NativeSearchIndex


def mark_search_change(session: Session, reference_id: uuid.UUID) -> None:
    """Allocate a commit-ordered generation inside the reference transaction.

    A sequence or timestamp alone can miss transactions that commit out of
    order. Updating this singleton holds its row lock until commit/rollback.
    The change table retains only the latest generation for each reference.
    """
    insert = (
        sqlite_insert
        if session.get_bind().dialect.name == "sqlite"
        else postgres_insert
    )
    session.execute(
        insert(ReferenceSearchState)
        .values(id=1, generation=0)
        .on_conflict_do_nothing(index_elements=["id"])
    )
    generation = session.scalar(
        update(ReferenceSearchState)
        .where(ReferenceSearchState.id == 1)
        .values(generation=ReferenceSearchState.generation + 1)
        .returning(ReferenceSearchState.generation)
    )
    session.execute(
        insert(ReferenceSearchChange)
        .values(reference_id=reference_id, generation=generation)
        .on_conflict_do_update(
            index_elements=["reference_id"], set_={"generation": generation}
        )
    )


def timestamp(value: datetime | None) -> int | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    delta = value - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (
        delta.days * 86400 + delta.seconds
    ) * 1_000_000 + delta.microseconds


class ReferenceSearch:
    def __init__(self) -> None:
        self._lock = Lock()
        self._index: NativeSearchIndex | None = None
        self._generation = -1

    def search(
        self, session: Session, **request: Any
    ) -> tuple[list[uuid.UUID], int]:
        with self._lock:
            try:
                self._synchronize(session)
                assert self._index is not None
                page = self._index.search(request)
            except Exception:
                # A failed commit/reload must never expose a partly updated index.
                self._index = None
                self._generation = -1
                raise
        return [uuid.UUID(value) for value in page["ids"]], int(page["total"])

    def _synchronize(self, session: Session) -> None:
        generation = (
            session.scalar(
                select(ReferenceSearchState.generation).where(
                    ReferenceSearchState.id == 1
                )
            )
            or 0
        )
        if self._index is not None and generation == self._generation:
            return
        if self._index is None or generation < self._generation:
            self._index = NativeSearchIndex()
            ids = session.scalars(select(ReferenceRecord.id)).all()
        else:
            # Do not cap by the observed generation: a later writer may replace
            # a change row between these two reads. We can safely replay it.
            ids = session.scalars(
                select(ReferenceSearchChange.reference_id).where(
                    ReferenceSearchChange.generation > self._generation
                )
            ).all()
        for start in range(0, len(ids), 256):
            batch = ids[start : start + 256]
            rows = session.execute(
                select(ReferenceRecord, UserRecord.email)
                .outerjoin(
                    UserRecord,
                    ReferenceRecord.created_by_user_id == UserRecord.id,
                )
                .where(ReferenceRecord.id.in_(batch))
                .execution_options(populate_existing=True)
            ).all()
            documents = [_document(record, email) for record, email in rows]
            present = {record.id for record, _email in rows}
            self._index.apply(
                documents,
                [str(value) for value in batch if value not in present],
            )
        self._generation = generation


def _document(record: ReferenceRecord, email: str | None) -> dict[str, Any]:
    venue = record.semantic_data.get("venue") or {}
    venue = venue.get("value") or {}
    venues = [
        record.venue_raw,
        record.venue_name,
        venue.get("full_name"),
        venue.get("short_name"),
    ]
    body = [record.canonical_bibtex]
    for field in record.semantic_data.get("extra_fields", []):
        value = field.get("value", {})
        body.append(value.get("resolved") or value.get("raw") or "")
    body.extend(context.context_text for context in record.citation_contexts)
    return {
        "id": str(record.id),
        "title": record.title or "",
        "authors": [person.display_name for person in record.contributors],
        "author_aliases": [
            " ".join(
                [
                    *person.name_prefixes,
                    *person.family_names,
                    *person.given_names,
                    *person.name_suffixes,
                ]
            )
            for person in record.contributors
            if not person.literal_name
            and person.family_names
            and person.given_names
        ],
        "venues": list(dict.fromkeys(value for value in venues if value)),
        "identifiers": [
            record.citation_key,
            *[
                identifier.normalized_value
                for identifier in record.identifiers
            ],
        ],
        "body": "\n".join(body),
        "year": record.publication_year,
        "entry_type": record.entry_type,
        "created_by": email or "",
        "updated_at": timestamp(record.updated_at),
    }

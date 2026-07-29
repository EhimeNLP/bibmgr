"""Transactional bibliography library operations."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import uuid
from typing import Any, Protocol

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db_models import (
    CitationContextRecord,
    ReferenceAuditEvent,
    ReferenceContributor,
    ReferenceHistoryHead,
    ReferenceIdentifier,
    ReferenceRecord,
    ReferenceUrl,
    UserRecord,
    utc_now,
)
from .models import (
    CitationContextInput,
    CitationContextResponse,
    ReferenceResponse,
)


class RegistrationEngine(Protocol):
    def validate_for_registration(
        self,
        source: str,
        policy: str,
        *,
        venue_registry: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...


class LibraryError(RuntimeError):
    code = "library_error"
    status_code = 500

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.details = details or {}


class ReferenceNotFoundError(LibraryError):
    code = "reference_not_found"
    status_code = 404


class DuplicateReferenceError(LibraryError):
    code = "duplicate_reference"
    status_code = 409


class StaleReferenceError(LibraryError):
    code = "stale_reference"
    status_code = 409


class StaleReferenceHistoryError(LibraryError):
    code = "stale_reference_history"
    status_code = 409


class ReferenceHistoryNotFoundError(LibraryError):
    code = "reference_history_not_found"
    status_code = 404


class ReferenceRevisionNotFoundError(LibraryError):
    code = "reference_revision_not_found"
    status_code = 404


class ReferenceRevisionNotRestorableError(LibraryError):
    code = "reference_revision_not_restorable"
    status_code = 422


class RegistrationRejectedError(LibraryError):
    code = "registration_rejected"
    status_code = 422


class InvalidRegistrationResultError(LibraryError):
    code = "invalid_registration_result"
    status_code = 500


class ReferenceLibrary:
    def __init__(self, engine: RegistrationEngine) -> None:
        self.engine = engine

    def search(
        self,
        session: Session,
        query: str,
        *,
        limit: int,
        offset: int,
        year: int | None = None,
        author: str | None = None,
        venue: str | None = None,
        identifier: str | None = None,
        entry_type: str | None = None,
        created_by: str | None = None,
        updated_from: datetime | None = None,
        updated_to: datetime | None = None,
        sort: str = "updated_desc",
    ) -> list[ReferenceRecord]:
        statement = self._search_statement(
            query,
            year=year,
            author=author,
            venue=venue,
            identifier=identifier,
            entry_type=entry_type,
            created_by=created_by,
            updated_from=updated_from,
            updated_to=updated_to,
            sort=sort,
        )
        statement = statement.offset(offset).limit(limit)
        return list(session.scalars(statement).unique())

    def search_page(
        self,
        session: Session,
        query: str,
        *,
        limit: int,
        offset: int,
        year: int | None = None,
        author: str | None = None,
        venue: str | None = None,
        identifier: str | None = None,
        entry_type: str | None = None,
        created_by: str | None = None,
        updated_from: datetime | None = None,
        updated_to: datetime | None = None,
        sort: str = "updated_desc",
    ) -> tuple[list[ReferenceRecord], int]:
        statement = self._search_statement(
            query,
            year=year,
            author=author,
            venue=venue,
            identifier=identifier,
            entry_type=entry_type,
            created_by=created_by,
            updated_from=updated_from,
            updated_to=updated_to,
            sort=sort,
        )
        id_query = statement.with_only_columns(ReferenceRecord.id).order_by(
            None
        )
        total = session.scalar(
            select(func.count()).select_from(id_query.subquery())
        )
        records = list(
            session.scalars(statement.offset(offset).limit(limit)).unique()
        )
        return records, int(total or 0)

    def _search_statement(
        self,
        query: str,
        *,
        year: int | None,
        author: str | None,
        venue: str | None,
        identifier: str | None,
        entry_type: str | None,
        created_by: str | None,
        updated_from: datetime | None,
        updated_to: datetime | None,
        sort: str,
    ) -> Select[tuple[ReferenceRecord]]:
        statement: Select[tuple[ReferenceRecord]] = select(ReferenceRecord)
        normalized_query = query.strip()
        normalized_author = (author or "").strip()
        normalized_identifier = (identifier or "").strip()
        if normalized_query or normalized_author:
            statement = statement.outerjoin(ReferenceRecord.contributors)
        if normalized_query or normalized_identifier:
            statement = statement.outerjoin(ReferenceRecord.identifiers)
        if normalized_query:
            pattern = f"%{_escape_like(normalized_query)}%"
            statement = statement.where(
                or_(
                    ReferenceRecord.title.ilike(pattern, escape="\\"),
                    ReferenceRecord.citation_key.ilike(
                        pattern, escape="\\"
                    ),
                    ReferenceRecord.venue_raw.ilike(pattern, escape="\\"),
                    ReferenceRecord.venue_name.ilike(pattern, escape="\\"),
                    ReferenceRecord.canonical_bibtex.ilike(
                        pattern, escape="\\"
                    ),
                    ReferenceContributor.display_name.ilike(
                        pattern, escape="\\"
                    ),
                    ReferenceIdentifier.normalized_value.ilike(
                        pattern, escape="\\"
                    ),
                )
            )
        if year is not None:
            statement = statement.where(
                ReferenceRecord.publication_year == year
            )
        if normalized_author:
            statement = statement.where(
                ReferenceContributor.display_name.ilike(
                    f"%{_escape_like(normalized_author)}%", escape="\\"
                )
            )
        normalized_venue = (venue or "").strip()
        if normalized_venue:
            venue_pattern = f"%{_escape_like(normalized_venue)}%"
            statement = statement.where(
                or_(
                    ReferenceRecord.venue_raw.ilike(
                        venue_pattern, escape="\\"
                    ),
                    ReferenceRecord.venue_name.ilike(
                        venue_pattern, escape="\\"
                    ),
                )
            )
        if normalized_identifier:
            identifier_pattern = (
                f"%{_escape_like(normalized_identifier)}%"
            )
            statement = statement.where(
                or_(
                    ReferenceIdentifier.normalized_value.ilike(
                        identifier_pattern, escape="\\"
                    ),
                    ReferenceRecord.citation_key.ilike(
                        identifier_pattern, escape="\\"
                    ),
                )
            )
        normalized_entry_type = (entry_type or "").strip()
        if normalized_entry_type:
            statement = statement.where(
                ReferenceRecord.entry_type
                == normalized_entry_type.casefold()
            )
        normalized_creator = (created_by or "").strip()
        if normalized_creator:
            creator_ids = select(UserRecord.id).where(
                UserRecord.email.ilike(
                    f"%{_escape_like(normalized_creator)}%", escape="\\"
                )
            )
            statement = statement.where(
                ReferenceRecord.created_by_user_id.in_(creator_ids)
            )
        if updated_from is not None:
            statement = statement.where(
                ReferenceRecord.updated_at >= updated_from
            )
        if updated_to is not None:
            statement = statement.where(
                ReferenceRecord.updated_at <= updated_to
            )

        order = {
            "updated_desc": (
                ReferenceRecord.updated_at.desc(),
                ReferenceRecord.id,
            ),
            "updated_asc": (
                ReferenceRecord.updated_at.asc(),
                ReferenceRecord.id,
            ),
            "year_desc": (
                ReferenceRecord.publication_year.desc().nullslast(),
                ReferenceRecord.title.asc(),
                ReferenceRecord.id,
            ),
            "year_asc": (
                ReferenceRecord.publication_year.asc().nullslast(),
                ReferenceRecord.title.asc(),
                ReferenceRecord.id,
            ),
            "title_asc": (
                ReferenceRecord.title.asc().nullslast(),
                ReferenceRecord.id,
            ),
        }[sort]
        return statement.distinct().order_by(*order)

    def get(
        self, session: Session, reference_id: uuid.UUID
    ) -> ReferenceRecord:
        record = session.get(ReferenceRecord, reference_id)
        if record is None:
            raise ReferenceNotFoundError("Reference not found.")
        return record

    def get_for_update(
        self, session: Session, reference_id: uuid.UUID
    ) -> ReferenceRecord:
        record = session.scalar(
            select(ReferenceRecord)
            .where(ReferenceRecord.id == reference_id)
            .with_for_update()
        )
        if record is None:
            raise ReferenceNotFoundError("Reference not found.")
        return record

    def list_history(
        self,
        session: Session,
        *,
        limit: int,
        offset: int,
    ) -> list[
        tuple[
            ReferenceHistoryHead,
            ReferenceAuditEvent,
            uuid.UUID | None,
        ]
    ]:
        statement = (
            select(
                ReferenceHistoryHead,
                ReferenceAuditEvent,
                ReferenceRecord.id,
            )
            .join(
                ReferenceAuditEvent,
                and_(
                    ReferenceAuditEvent.reference_id
                    == ReferenceHistoryHead.reference_id,
                    ReferenceAuditEvent.revision
                    == ReferenceHistoryHead.latest_revision,
                ),
            )
            .outerjoin(
                ReferenceRecord,
                ReferenceRecord.id
                == ReferenceHistoryHead.reference_id,
            )
            .order_by(
                ReferenceHistoryHead.updated_at.desc(),
                ReferenceHistoryHead.reference_id,
            )
            .offset(offset)
            .limit(limit)
        )
        return [
            (head, event, live_reference_id)
            for head, event, live_reference_id in session.execute(
                statement
            )
        ]

    def count_history(self, session: Session) -> int:
        return int(
            session.scalar(
                select(func.count())
                .select_from(ReferenceHistoryHead)
                .join(
                    ReferenceAuditEvent,
                    and_(
                        ReferenceAuditEvent.reference_id
                        == ReferenceHistoryHead.reference_id,
                        ReferenceAuditEvent.revision
                        == ReferenceHistoryHead.latest_revision,
                    ),
                )
            )
            or 0
        )

    def get_history(
        self,
        session: Session,
        reference_id: uuid.UUID,
    ) -> tuple[
        ReferenceHistoryHead,
        list[ReferenceAuditEvent],
        bool,
    ]:
        head = session.get(ReferenceHistoryHead, reference_id)
        if head is None or head.latest_revision == 0:
            raise ReferenceHistoryNotFoundError(
                "Reference history not found."
            )
        events = list(
            session.scalars(
                select(ReferenceAuditEvent)
                .where(
                    ReferenceAuditEvent.reference_id == reference_id
                )
                .order_by(ReferenceAuditEvent.revision.desc())
            )
        )
        exists = session.get(ReferenceRecord, reference_id) is not None
        return head, events, exists

    def restore(
        self,
        session: Session,
        *,
        reference_id: uuid.UUID,
        target_revision: int,
        expected_head_revision: int,
        actor_user_id: uuid.UUID,
    ) -> ReferenceRecord:
        head = session.scalar(
            select(ReferenceHistoryHead)
            .where(
                ReferenceHistoryHead.reference_id == reference_id
            )
            .with_for_update()
        )
        if head is None or head.latest_revision == 0:
            raise ReferenceHistoryNotFoundError(
                "Reference history not found."
            )
        if head.latest_revision != expected_head_revision:
            raise StaleReferenceHistoryError(
                "Reference history has changed since it was loaded.",
                details={"head_revision": head.latest_revision},
            )

        target = session.scalar(
            select(ReferenceAuditEvent).where(
                ReferenceAuditEvent.reference_id == reference_id,
                ReferenceAuditEvent.revision == target_revision,
            )
        )
        if target is None:
            raise ReferenceRevisionNotFoundError(
                "Reference revision not found."
            )
        if not _is_complete_snapshot(target.after_data):
            raise ReferenceRevisionNotRestorableError(
                "The selected revision does not contain a restorable record."
            )

        current = session.scalar(
            select(ReferenceRecord)
            .where(ReferenceRecord.id == reference_id)
            .with_for_update()
        )
        before_data = (
            _audit_snapshot(current) if current is not None else None
        )
        restored = _restore_snapshot(
            session,
            reference_id=reference_id,
            current=current,
            snapshot=target.after_data,
            actor_user_id=actor_user_id,
        )
        self._flush_or_duplicate(session)
        _append_history_event(
            session,
            head=head,
            actor_user_id=actor_user_id,
            action="restore",
            before_data=before_data,
            after_data=_audit_snapshot(
                restored,
                submitted_bibtex=_snapshot_submitted_bibtex(
                    target.after_data
                ),
            ),
            restored_from_revision=target_revision,
        )
        session.flush()
        return restored

    def register(
        self,
        session: Session,
        *,
        bibtex: str,
        source: str,
        policy: str,
        actor_user_id: uuid.UUID,
        citation_contexts: list[CitationContextInput] | None = None,
        venue_registry: dict[str, Any] | None = None,
    ) -> list[ReferenceRecord]:
        # Materialize the database transaction before authoritative validation.
        session.connection()
        validation = self.engine.validate_for_registration(
            bibtex, policy, venue_registry=venue_registry
        )
        if not validation.get("accepted", False):
            raise RegistrationRejectedError(
                "BibTeX is not eligible for registration.",
                details={
                    "diagnostics": validation.get("diagnostics", []),
                    "source_revision": validation.get("source_revision"),
                    "unresolved_semantics": validation.get(
                        "unresolved_semantics", False
                    ),
                },
            )

        bibliography = validation.get("bibliography")
        records = (
            bibliography.get("records")
            if isinstance(bibliography, dict)
            else None
        )
        if not isinstance(records, list):
            raise InvalidRegistrationResultError(
                "Native registration returned an incomplete bibliography."
            )
        if not records:
            raise RegistrationRejectedError(
                "BibTeX does not contain a bibliographic entry."
            )
        contexts = citation_contexts or []
        if contexts and len(records) != 1:
            raise RegistrationRejectedError(
                "Citation contexts can only accompany a single BibTeX entry."
            )

        created: list[tuple[ReferenceRecord, str]] = []
        for semantic_record in records:
            if not isinstance(semantic_record, dict):
                raise InvalidRegistrationResultError(
                    "Native registration returned a non-object record."
                )
            stored_entry = _record_source(
                bibtex, semantic_record, len(records)
            )
            record = _new_record(
                semantic_record,
                canonical_bibtex=stored_entry,
                registration_source=source,
                actor_user_id=actor_user_id,
            )
            if contexts:
                _append_citation_contexts(record, contexts)
            session.add(record)
            created.append((record, stored_entry))

        self._flush_or_duplicate(session)
        for record, submitted_entry in created:
            head = _new_history_head(session, record.id)
            _append_history_event(
                session,
                head=head,
                actor_user_id=actor_user_id,
                action="create",
                before_data=None,
                after_data=_audit_snapshot(
                    record, submitted_bibtex=submitted_entry
                ),
            )
        session.flush()
        return [record for record, _submitted_entry in created]

    def update(
        self,
        session: Session,
        *,
        reference_id: uuid.UUID,
        bibtex: str,
        source_revision: str,
        policy: str,
        actor_user_id: uuid.UUID,
        venue_registry: dict[str, Any] | None = None,
    ) -> ReferenceRecord:
        session.connection()
        record = self.get_for_update(session, reference_id)
        head = _ensure_history_head(
            session,
            record=record,
            actor_user_id=actor_user_id,
        )
        if record.source_revision != source_revision:
            raise StaleReferenceError(
                "The reference has changed since it was loaded.",
                details={"source_revision": record.source_revision},
            )

        before_data = _audit_snapshot(record)
        validation = self.engine.validate_for_registration(
            bibtex, policy, venue_registry=venue_registry
        )
        if not validation.get("accepted", False):
            raise RegistrationRejectedError(
                "BibTeX is not eligible for registration.",
                details={
                    "diagnostics": validation.get("diagnostics", []),
                    "source_revision": validation.get("source_revision"),
                    "unresolved_semantics": validation.get(
                        "unresolved_semantics", False
                    ),
                },
            )

        bibliography = validation.get("bibliography")
        semantic_records = (
            bibliography.get("records")
            if isinstance(bibliography, dict)
            else None
        )
        if (
            not isinstance(semantic_records, list)
            or len(semantic_records) != 1
            or not isinstance(semantic_records[0], dict)
        ):
            raise RegistrationRejectedError(
                "Editing requires exactly one bibliographic entry."
            )

        record.contributors.clear()
        record.identifiers.clear()
        record.urls.clear()
        session.flush()
        _apply_semantic_record(
            record,
            semantic_records[0],
            canonical_bibtex=bibtex,
            registration_source="edit",
        )
        record.updated_by_user_id = actor_user_id
        record.updated_at = utc_now()
        self._flush_or_duplicate(session)
        _append_history_event(
            session,
            head=head,
            actor_user_id=actor_user_id,
            action="update",
            before_data=before_data,
            after_data=_audit_snapshot(
                record, submitted_bibtex=bibtex
            ),
        )
        session.flush()
        return record

    def add_citation_contexts(
        self,
        session: Session,
        *,
        reference_id: uuid.UUID,
        contexts: list[CitationContextInput],
        actor_user_id: uuid.UUID,
    ) -> ReferenceRecord:
        record = self.get_for_update(session, reference_id)
        head = _ensure_history_head(
            session,
            record=record,
            actor_user_id=actor_user_id,
        )
        before_data = _audit_snapshot(record)
        _append_citation_contexts(record, contexts)
        record.updated_by_user_id = actor_user_id
        record.updated_at = utc_now()
        session.flush()
        _append_history_event(
            session,
            head=head,
            actor_user_id=actor_user_id,
            action="context",
            before_data=before_data,
            after_data=_audit_snapshot(record),
        )
        session.flush()
        return record

    def delete(
        self,
        session: Session,
        *,
        reference_id: uuid.UUID,
        expected_source_revision: str,
        actor_user_id: uuid.UUID,
    ) -> None:
        record = self.get_for_update(session, reference_id)
        if record.source_revision != expected_source_revision:
            raise StaleReferenceError(
                "The reference has changed since it was loaded.",
                details={"source_revision": record.source_revision},
            )
        head = _ensure_history_head(
            session,
            record=record,
            actor_user_id=actor_user_id,
        )
        _append_history_event(
            session,
            head=head,
            actor_user_id=actor_user_id,
            action="delete",
            before_data=_audit_snapshot(record),
            after_data=None,
        )
        session.delete(record)
        session.flush()

    @staticmethod
    def _flush_or_duplicate(session: Session) -> None:
        try:
            session.flush()
        except IntegrityError as error:
            raise DuplicateReferenceError(
                "A reference with the same DOI or arXiv identifier already exists."
            ) from error

def reference_response(record: ReferenceRecord) -> ReferenceResponse:
    authors = [
        contributor.display_name
        for contributor in record.contributors
        if contributor.role == "author"
    ]
    primary_doi = next(
        (
            identifier.normalized_value
            for identifier in record.identifiers
            if identifier.scheme == "doi"
        ),
        None,
    )
    primary_url = record.urls[0].url if record.urls else None
    contexts = [
        CitationContextResponse(
            id=str(context.id),
            source_paper_title=context.source_paper_title,
            source_file_name=context.source_file_name,
            before=context.before_text,
            context=context.context_text,
            after=context.after_text,
        )
        for context in record.citation_contexts
    ]
    return ReferenceResponse(
        id=str(record.id),
        title=normalize_title_for_display(record.title) or record.citation_key,
        authors=authors,
        year=record.publication_year,
        venue=record.venue_raw or record.venue_name,
        doi=primary_doi,
        url=primary_url,
        bibtex_key=record.citation_key,
        bibtex=record.canonical_bibtex,
        source_revision=record.source_revision,
        citation_contexts=contexts,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _new_record(
    semantic_record: dict[str, Any],
    *,
    canonical_bibtex: str,
    registration_source: str,
    actor_user_id: uuid.UUID,
) -> ReferenceRecord:
    record = ReferenceRecord(
        created_by_user_id=actor_user_id,
        updated_by_user_id=actor_user_id,
    )
    _apply_semantic_record(
        record,
        semantic_record,
        canonical_bibtex=canonical_bibtex,
        registration_source=registration_source,
    )
    return record


def _append_citation_contexts(
    record: ReferenceRecord,
    contexts: list[CitationContextInput],
) -> None:
    for context in contexts:
        record.citation_contexts.append(
            CitationContextRecord(
                source_paper_title=context.source_paper_title,
                source_file_name=context.source_file_name,
                before_text=context.before,
                context_text=context.context,
                after_text=context.after,
            )
        )


def _audit_snapshot(
    record: ReferenceRecord,
    *,
    submitted_bibtex: str | None = None,
) -> dict[str, Any]:
    canonical_bibtex = record.canonical_bibtex
    return {
        "snapshot_version": 2,
        "id": str(record.id),
        "citation_key": record.citation_key,
        "entry_type": record.entry_type,
        "work_type": record.work_type,
        "title": record.title,
        "publication_year": record.publication_year,
        "publication_date_raw": record.publication_date_raw,
        "venue_raw": record.venue_raw,
        "venue_id": record.venue_id,
        "venue_name": record.venue_name,
        "canonical_bibtex": canonical_bibtex,
        "submitted_bibtex": submitted_bibtex or canonical_bibtex,
        "source_revision": record.source_revision,
        "registration_source": record.registration_source,
        "created_by_user_id": (
            str(record.created_by_user_id)
            if record.created_by_user_id
            else None
        ),
        "updated_by_user_id": (
            str(record.updated_by_user_id)
            if record.updated_by_user_id
            else None
        ),
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "semantic_data": record.semantic_data,
        "contributors": [
            {
                "role": contributor.role,
                "position": contributor.position,
                "display_name": contributor.display_name,
                "given_names": contributor.given_names,
                "family_names": contributor.family_names,
                "name_prefixes": contributor.name_prefixes,
                "name_suffixes": contributor.name_suffixes,
                "literal_name": contributor.literal_name,
                "semantic_data": contributor.semantic_data,
            }
            for contributor in record.contributors
        ],
        "identifiers": [
            {
                "scheme": identifier.scheme,
                "position": identifier.position,
                "value": identifier.value,
                "normalized_value": identifier.normalized_value,
                "semantic_data": identifier.semantic_data,
            }
            for identifier in record.identifiers
        ],
        "urls": [
            {
                "position": url.position,
                "url": url.url,
                "semantic_data": url.semantic_data,
            }
            for url in record.urls
        ],
        "citation_contexts": [
            {
                "id": str(context.id),
                "source_paper_title": context.source_paper_title,
                "source_file_name": context.source_file_name,
                "before_text": context.before_text,
                "context_text": context.context_text,
                "after_text": context.after_text,
                "created_at": context.created_at.isoformat(),
            }
            for context in record.citation_contexts
        ],
    }


def _new_history_head(
    session: Session, reference_id: uuid.UUID
) -> ReferenceHistoryHead:
    head = ReferenceHistoryHead(
        reference_id=reference_id,
        latest_revision=0,
        updated_at=utc_now(),
    )
    session.add(head)
    session.flush()
    return head


def _ensure_history_head(
    session: Session,
    *,
    record: ReferenceRecord,
    actor_user_id: uuid.UUID,
) -> ReferenceHistoryHead:
    head = session.scalar(
        select(ReferenceHistoryHead)
        .where(ReferenceHistoryHead.reference_id == record.id)
        .with_for_update()
    )
    if head is None:
        head = _new_history_head(session, record.id)

    latest_event = (
        session.scalar(
            select(ReferenceAuditEvent).where(
                ReferenceAuditEvent.reference_id == record.id,
                ReferenceAuditEvent.revision == head.latest_revision,
            )
        )
        if head.latest_revision > 0
        else None
    )
    if latest_event is None or not _is_complete_snapshot(
        latest_event.after_data
    ):
        _append_history_event(
            session,
            head=head,
            actor_user_id=actor_user_id,
            action="baseline",
            before_data=None,
            after_data=_audit_snapshot(record),
        )
        session.flush()
    return head


def _append_history_event(
    session: Session,
    *,
    head: ReferenceHistoryHead,
    actor_user_id: uuid.UUID,
    action: str,
    before_data: dict[str, Any] | None,
    after_data: dict[str, Any] | None,
    restored_from_revision: int | None = None,
) -> ReferenceAuditEvent:
    head.latest_revision += 1
    head.updated_at = utc_now()
    event = ReferenceAuditEvent(
        reference_id=head.reference_id,
        actor_user_id=actor_user_id,
        revision=head.latest_revision,
        action=action,
        restored_from_revision=restored_from_revision,
        before_data=before_data,
        after_data=after_data,
        occurred_at=head.updated_at,
    )
    session.add(event)
    return event


def _is_complete_snapshot(
    snapshot: dict[str, Any] | None,
) -> bool:
    return (
        isinstance(snapshot, dict)
        and snapshot.get("snapshot_version") in (1, 2)
        and isinstance(_snapshot_canonical_bibtex(snapshot), str)
        and isinstance(snapshot.get("semantic_data"), dict)
        and isinstance(snapshot.get("contributors"), list)
        and isinstance(snapshot.get("identifiers"), list)
        and isinstance(snapshot.get("urls"), list)
        and isinstance(snapshot.get("citation_contexts"), list)
    )


def _snapshot_canonical_bibtex(
    snapshot: dict[str, Any] | None,
) -> str | None:
    if not isinstance(snapshot, dict):
        return None
    canonical = snapshot.get("canonical_bibtex")
    if isinstance(canonical, str):
        return canonical
    legacy = snapshot.get("raw_bibtex")
    return legacy if isinstance(legacy, str) else None


def _snapshot_submitted_bibtex(
    snapshot: dict[str, Any] | None,
) -> str | None:
    if not isinstance(snapshot, dict):
        return None
    submitted = snapshot.get("submitted_bibtex")
    if isinstance(submitted, str):
        return submitted
    return _snapshot_canonical_bibtex(snapshot)


def _restore_snapshot(
    session: Session,
    *,
    reference_id: uuid.UUID,
    current: ReferenceRecord | None,
    snapshot: dict[str, Any],
    actor_user_id: uuid.UUID,
) -> ReferenceRecord:
    if not _is_complete_snapshot(snapshot):
        raise ReferenceRevisionNotRestorableError(
            "The selected revision does not contain a complete snapshot."
        )

    record = current or ReferenceRecord(id=reference_id)
    if current is not None:
        record.contributors.clear()
        record.identifiers.clear()
        record.urls.clear()
        record.citation_contexts.clear()
        session.flush()
    else:
        session.add(record)

    record.citation_key = _required_snapshot_string(
        snapshot, "citation_key"
    )
    record.entry_type = _required_snapshot_string(snapshot, "entry_type")
    record.work_type = _required_snapshot_string(snapshot, "work_type")
    record.title = normalize_title_for_display(
        _optional_snapshot_string(snapshot, "title")
    )
    record.publication_year = _optional_snapshot_integer(
        snapshot, "publication_year"
    )
    record.publication_date_raw = _optional_snapshot_string(
        snapshot, "publication_date_raw"
    )
    record.venue_raw = _optional_snapshot_string(snapshot, "venue_raw")
    record.venue_id = _optional_snapshot_string(snapshot, "venue_id")
    record.venue_name = _optional_snapshot_string(snapshot, "venue_name")
    canonical_bibtex = _snapshot_canonical_bibtex(snapshot)
    if canonical_bibtex is None:
        raise ReferenceRevisionNotRestorableError(
            "The selected revision has invalid canonical BibTeX."
        )
    record.canonical_bibtex = canonical_bibtex
    record.source_revision = _required_snapshot_string(
        snapshot, "source_revision"
    )
    record.registration_source = _required_snapshot_string(
        snapshot, "registration_source"
    )
    semantic_data = snapshot.get("semantic_data")
    if not isinstance(semantic_data, dict):
        raise ReferenceRevisionNotRestorableError(
            "The selected revision has invalid semantic data."
        )
    record.semantic_data = semantic_data
    record.created_by_user_id = _optional_snapshot_uuid(
        snapshot, "created_by_user_id"
    )
    record.updated_by_user_id = actor_user_id
    record.created_at = _snapshot_datetime(snapshot, "created_at")
    record.updated_at = utc_now()

    for contributor in _snapshot_objects(snapshot, "contributors"):
        record.contributors.append(
            ReferenceContributor(
                role=_required_snapshot_string(contributor, "role"),
                position=_required_snapshot_integer(
                    contributor, "position"
                ),
                display_name=_required_snapshot_string(
                    contributor, "display_name"
                ),
                given_names=_snapshot_strings(
                    contributor, "given_names"
                ),
                family_names=_snapshot_strings(
                    contributor, "family_names"
                ),
                name_prefixes=_snapshot_strings(
                    contributor, "name_prefixes"
                ),
                name_suffixes=_snapshot_strings(
                    contributor, "name_suffixes"
                ),
                literal_name=_optional_snapshot_string(
                    contributor, "literal_name"
                ),
                semantic_data=_required_snapshot_object(
                    contributor, "semantic_data"
                ),
            )
        )

    for identifier in _snapshot_objects(snapshot, "identifiers"):
        record.identifiers.append(
            ReferenceIdentifier(
                scheme=_required_snapshot_string(
                    identifier, "scheme"
                ),
                position=_required_snapshot_integer(
                    identifier, "position"
                ),
                value=_required_snapshot_string(identifier, "value"),
                normalized_value=_required_snapshot_string(
                    identifier, "normalized_value"
                ),
                semantic_data=_required_snapshot_object(
                    identifier, "semantic_data"
                ),
            )
        )

    for url in _snapshot_objects(snapshot, "urls"):
        record.urls.append(
            ReferenceUrl(
                position=_required_snapshot_integer(url, "position"),
                url=_required_snapshot_string(url, "url"),
                semantic_data=_required_snapshot_object(
                    url, "semantic_data"
                ),
            )
        )

    for context in _snapshot_objects(snapshot, "citation_contexts"):
        record.citation_contexts.append(
            CitationContextRecord(
                id=_required_snapshot_uuid(context, "id"),
                source_paper_title=_optional_snapshot_string(
                    context, "source_paper_title"
                ),
                source_file_name=_optional_snapshot_string(
                    context, "source_file_name"
                ),
                before_text=_optional_snapshot_string(
                    context, "before_text"
                ),
                context_text=_required_snapshot_string(
                    context, "context_text"
                ),
                after_text=_optional_snapshot_string(
                    context, "after_text"
                ),
                created_at=_snapshot_datetime(context, "created_at"),
            )
        )
    return record


def _snapshot_objects(
    snapshot: dict[str, Any], key: str
) -> list[dict[str, Any]]:
    value = snapshot.get(key)
    if not isinstance(value, list) or not all(
        isinstance(item, dict) for item in value
    ):
        raise ReferenceRevisionNotRestorableError(
            f"The selected revision has invalid {key}."
        )
    return value


def _snapshot_strings(
    snapshot: dict[str, Any], key: str
) -> list[str]:
    value = snapshot.get(key)
    if not isinstance(value, list) or not all(
        isinstance(item, str) for item in value
    ):
        raise ReferenceRevisionNotRestorableError(
            f"The selected revision has invalid {key}."
        )
    return value


def _required_snapshot_object(
    snapshot: dict[str, Any], key: str
) -> dict[str, Any]:
    value = snapshot.get(key)
    if not isinstance(value, dict):
        raise ReferenceRevisionNotRestorableError(
            f"The selected revision has invalid {key}."
        )
    return value


def _required_snapshot_string(
    snapshot: dict[str, Any], key: str
) -> str:
    value = snapshot.get(key)
    if not isinstance(value, str):
        raise ReferenceRevisionNotRestorableError(
            f"The selected revision has invalid {key}."
        )
    return value


def _optional_snapshot_string(
    snapshot: dict[str, Any], key: str
) -> str | None:
    value = snapshot.get(key)
    if value is not None and not isinstance(value, str):
        raise ReferenceRevisionNotRestorableError(
            f"The selected revision has invalid {key}."
        )
    return value


def _required_snapshot_integer(
    snapshot: dict[str, Any], key: str
) -> int:
    value = snapshot.get(key)
    if not isinstance(value, int):
        raise ReferenceRevisionNotRestorableError(
            f"The selected revision has invalid {key}."
        )
    return value


def _optional_snapshot_integer(
    snapshot: dict[str, Any], key: str
) -> int | None:
    value = snapshot.get(key)
    if value is not None and not isinstance(value, int):
        raise ReferenceRevisionNotRestorableError(
            f"The selected revision has invalid {key}."
        )
    return value


def _required_snapshot_uuid(
    snapshot: dict[str, Any], key: str
) -> uuid.UUID:
    value = _required_snapshot_string(snapshot, key)
    try:
        return uuid.UUID(value)
    except ValueError as error:
        raise ReferenceRevisionNotRestorableError(
            f"The selected revision has invalid {key}."
        ) from error


def _optional_snapshot_uuid(
    snapshot: dict[str, Any], key: str
) -> uuid.UUID | None:
    value = _optional_snapshot_string(snapshot, key)
    if value is None:
        return None
    try:
        return uuid.UUID(value)
    except ValueError as error:
        raise ReferenceRevisionNotRestorableError(
            f"The selected revision has invalid {key}."
        ) from error


def _snapshot_datetime(
    snapshot: dict[str, Any], key: str
) -> datetime:
    value = _required_snapshot_string(snapshot, key)
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise ReferenceRevisionNotRestorableError(
            f"The selected revision has invalid {key}."
        ) from error


def _apply_semantic_record(
    record: ReferenceRecord,
    semantic_record: dict[str, Any],
    *,
    canonical_bibtex: str,
    registration_source: str,
) -> None:
    citation_key = _string(_sourced_value(semantic_record, "citation_key"))
    entry_type = _string(_sourced_value(semantic_record, "entry_type"))
    work_type = _string(_sourced_value(semantic_record, "work_type"))
    if not citation_key or not entry_type or not work_type:
        raise InvalidRegistrationResultError(
            "Native registration record is missing its identity fields."
        )

    date_value = _sourced_value(semantic_record, "date")
    date = date_value if isinstance(date_value, dict) else {}
    venue_value = _sourced_value(semantic_record, "venue")
    venue = venue_value if isinstance(venue_value, dict) else {}

    record.citation_key = citation_key
    record.entry_type = entry_type
    record.work_type = work_type
    record.title = normalize_title_for_display(
        _string(_sourced_value(semantic_record, "title"))
    )
    record.publication_year = _integer(date.get("year"))
    record.publication_date_raw = _string(date.get("raw"))
    record.venue_raw = _string(venue.get("raw"))
    record.venue_id = _string(venue.get("venue_id"))
    record.venue_name = _string(
        venue.get("full_name") or venue.get("short_name")
    )
    record.canonical_bibtex = canonical_bibtex
    record.source_revision = _source_revision(canonical_bibtex)
    record.registration_source = registration_source
    record.semantic_data = semantic_record

    for role, field_name in (("author", "authors"), ("editor", "editors")):
        sourced_people = semantic_record.get(field_name, [])
        if not isinstance(sourced_people, list):
            continue
        for position, sourced_person in enumerate(sourced_people):
            if not isinstance(sourced_person, dict):
                continue
            person_value = sourced_person.get("value")
            if not isinstance(person_value, dict):
                continue
            record.contributors.append(
                ReferenceContributor(
                    role=role,
                    position=position,
                    display_name=_person_display_name(person_value),
                    given_names=_string_list(person_value.get("given")),
                    family_names=_string_list(person_value.get("family")),
                    name_prefixes=_string_list(person_value.get("prefix")),
                    name_suffixes=_string_list(person_value.get("suffix")),
                    literal_name=_string(person_value.get("literal")),
                    semantic_data=sourced_person,
                )
            )

    identifiers = semantic_record.get("identifiers")
    if isinstance(identifiers, dict):
        for semantic_key, scheme in (
            ("dois", "doi"),
            ("arxiv", "arxiv"),
            ("isbns", "isbn"),
            ("issns", "issn"),
        ):
            sourced_identifiers = identifiers.get(semantic_key, [])
            if not isinstance(sourced_identifiers, list):
                continue
            for position, sourced_identifier in enumerate(
                sourced_identifiers
            ):
                _append_identifier(
                    record,
                    scheme=scheme,
                    position=position,
                    sourced_identifier=sourced_identifier,
                )
        other_identifiers = identifiers.get("other", [])
        if isinstance(other_identifiers, list):
            for position, sourced_identifier in enumerate(other_identifiers):
                if not isinstance(sourced_identifier, dict):
                    continue
                identifier_value = sourced_identifier.get("value")
                if not isinstance(identifier_value, dict):
                    continue
                scheme = _string(identifier_value.get("scheme"))
                value = _string(identifier_value.get("value"))
                if scheme and value:
                    record.identifiers.append(
                        ReferenceIdentifier(
                            scheme=scheme.casefold(),
                            position=position,
                            value=value,
                            normalized_value=_normalize_identifier(value),
                            semantic_data=sourced_identifier,
                        )
                    )

    sourced_urls = semantic_record.get("urls", [])
    if isinstance(sourced_urls, list):
        for position, sourced_url in enumerate(sourced_urls):
            if not isinstance(sourced_url, dict):
                continue
            url = _string(sourced_url.get("value"))
            if url:
                record.urls.append(
                    ReferenceUrl(
                        position=position,
                        url=url,
                        semantic_data=sourced_url,
                    )
                )


def normalize_title_for_display(value: str | None) -> str | None:
    """Return plain display text without changing stored BibTeX semantics."""

    if value is None:
        return None
    output: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if (
            character == "\\"
            and index + 1 < len(value)
            and value[index + 1] in "{}"
        ):
            output.append(value[index + 1])
            index += 2
            continue
        if character not in "{}":
            output.append(character)
        index += 1
    normalized = " ".join("".join(output).split())
    return normalized or None


def _append_identifier(
    record: ReferenceRecord,
    *,
    scheme: str,
    position: int,
    sourced_identifier: Any,
) -> None:
    if not isinstance(sourced_identifier, dict):
        return
    value = _string(sourced_identifier.get("value"))
    if not value:
        return
    record.identifiers.append(
        ReferenceIdentifier(
            scheme=scheme,
            position=position,
            value=value,
            normalized_value=_normalize_identifier(value),
            semantic_data=sourced_identifier,
        )
    )


def _record_source(
    source: str, semantic_record: dict[str, Any], record_count: int
) -> str:
    if record_count == 1:
        return source
    origins = semantic_record.get("origins", [])
    if not isinstance(origins, list):
        raise InvalidRegistrationResultError(
            "Native registration record has no source range."
        )
    entry_origin = next(
        (
            origin
            for origin in origins
            if isinstance(origin, dict) and origin.get("kind") == "entry"
        ),
        None,
    )
    source_range = (
        entry_origin.get("range")
        if isinstance(entry_origin, dict)
        else None
    )
    if not isinstance(source_range, dict):
        raise InvalidRegistrationResultError(
            "Native registration record has no entry range."
        )
    start = _integer(source_range.get("start"))
    end = _integer(source_range.get("end"))
    encoded = source.encode("utf-8")
    if (
        start is None
        or end is None
        or start < 0
        or start >= end
        or end > len(encoded)
    ):
        raise InvalidRegistrationResultError(
            "Native registration record has an invalid entry range."
        )
    try:
        return encoded[start:end].decode("utf-8")
    except UnicodeDecodeError as error:
        raise InvalidRegistrationResultError(
            "Native registration range is not on a UTF-8 boundary."
        ) from error


def _sourced_value(record: dict[str, Any], field: str) -> Any:
    sourced = record.get(field)
    return sourced.get("value") if isinstance(sourced, dict) else None


def _person_display_name(person: dict[str, Any]) -> str:
    literal = _string(person.get("literal"))
    if literal:
        return literal
    parts = [
        *_string_list(person.get("given")),
        *_string_list(person.get("prefix")),
        *_string_list(person.get("family")),
    ]
    display = " ".join(parts)
    suffixes = _string_list(person.get("suffix"))
    if suffixes:
        display = f"{display}, {' '.join(suffixes)}" if display else " ".join(
            suffixes
        )
    return display or _string(person.get("raw")) or "Unknown contributor"


def _source_revision(source: str) -> str:
    return f"sha256:{sha256(source.encode('utf-8')).hexdigest()}"


def _normalize_identifier(value: str) -> str:
    return value.strip().casefold()


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    return value if isinstance(value, int) else None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]

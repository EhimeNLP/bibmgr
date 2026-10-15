"""Database candidate lookup and transactional duplicate policy enforcement.

All bibliographic interpretation and comparison stays in Rust. This adapter
stores disposable comparison keys and binds confirmations to the current input,
policy, and candidate revisions. It never modifies or merges existing records.
"""
from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any
import uuid

from sqlalchemy import delete, or_, select, text, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .db_models import ReferenceComparison, ReferenceComparisonKey, ReferenceRecord, ReferenceSearchState
from .native import NativeEngine

COMPARISON_VERSION = 1
MAX_CANDIDATES = 500


def lock_reference_writes(session: Session) -> None:
    """Serialize reference changes across workers until transaction completion.

    PostgreSQL READ COMMITTED sees the preceding writer after this lock. SQLite
    uses its writer lock. Acquire before any reference/history row locks.
    """
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(734518209)"))
    else:
        session.execute(sqlite_insert(ReferenceSearchState).values(id=1, generation=0).on_conflict_do_nothing())
        session.execute(update(ReferenceSearchState).where(ReferenceSearchState.id == 1).values(generation=ReferenceSearchState.generation))


def comparison_keys(profile: dict[str, Any]) -> set[str]:
    values = [(name, profile[name]) for name in ("title", "citation_key") if profile.get(name)]
    for name in ("dois", "arxiv_families"):
        values.extend((name, value) for value in profile.get(name, []))
    return {sha256(json.dumps(pair, ensure_ascii=False).encode()).hexdigest() for pair in values}


class DuplicateCheck:
    def __init__(self, policy: dict[str, Any] | None = None) -> None:
        if policy is None:
            path = os.environ.get("BIBMGR_DUPLICATE_POLICY_FILE")
            policy = json.loads(Path(path).read_text(encoding="utf-8")) if path else {}
        if not isinstance(policy, dict):
            raise ValueError("Duplicate policy must be a JSON object")
        self.policy = policy
        self._engine: NativeEngine | None = None
        if policy:
            self.policy = self.engine.assess_duplicates([], [], policy)["policy"]
            if self.policy["identifier"] != "reject":
                raise ValueError("Database DOI/arXiv uniqueness requires identifier=reject")

    @property
    def engine(self) -> NativeEngine:
        if self._engine is None:
            self._engine = NativeEngine()
        return self._engine

    def profiles(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.engine.comparison_records(records)

    def refresh(self, session: Session) -> None:
        stale = list(session.scalars(select(ReferenceRecord).outerjoin(
            ReferenceComparison, ReferenceRecord.id == ReferenceComparison.reference_id
        ).where(or_(ReferenceComparison.reference_id.is_(None),
                    ReferenceComparison.source_revision != ReferenceRecord.source_revision,
                    ReferenceComparison.version != COMPARISON_VERSION))))
        for offset in range(0, len(stale), 100):
            records = stale[offset:offset + 100]
            profiles = self.profiles([r.semantic_data for r in records])
            for record, profile in zip(records, profiles, strict=True):
                session.execute(delete(ReferenceComparisonKey).where(ReferenceComparisonKey.reference_id == record.id))
                session.merge(ReferenceComparison(reference_id=record.id, source_revision=record.source_revision,
                                                   version=COMPARISON_VERSION, profile=profile))
                session.flush()
                session.add_all(ReferenceComparisonKey(reference_id=record.id, key=key) for key in comparison_keys(profile))
            session.flush()

    def check(self, session: Session, records: list[dict[str, Any]], *, source: str,
              confirmation: str | None = None, exclude_id: uuid.UUID | None = None) -> list[dict[str, Any]]:
        # Import here to avoid a cycle with the library's shared HTTP error types.
        from .library import LibraryError

        profiles = self.profiles(records)
        self.refresh(session)
        keys = sorted({key for profile in profiles for key in comparison_keys(profile)})
        ids: set[uuid.UUID] = set()
        for offset in range(0, len(keys), 400):
            query = select(ReferenceComparisonKey.reference_id).where(ReferenceComparisonKey.key.in_(keys[offset:offset + 400])).distinct()
            if exclude_id is not None:
                query = query.where(ReferenceComparisonKey.reference_id != exclude_id)
            ids.update(session.scalars(query.limit(MAX_CANDIDATES + 1)))
            if len(ids) > MAX_CANDIDATES:
                error = LibraryError("Too many duplicate candidates; submit a smaller batch.")
                error.code, error.status_code = "duplicate_check_limit", 422
                raise error
        candidates = list(session.scalars(select(ReferenceRecord).where(ReferenceRecord.id.in_(ids)).order_by(ReferenceRecord.id))) if ids else []
        # Recompute from semantic data so displayed comparison and index agree.
        candidate_profiles = self.profiles([r.semantic_data for r in candidates])
        result = self.engine.assess_duplicates(profiles, candidate_profiles, self.policy)
        findings = result["findings"]
        for finding in findings:
            if finding["existing"]:
                record = candidates[finding["candidate_index"]]
                finding["reference_id"] = str(record.id)
                finding["citation_key"] = record.citation_key
                finding["title"] = record.title
                finding["source_revision"] = record.source_revision
            else:
                record_data = records[finding["candidate_index"]]
                finding["citation_key"] = record_data["citation_key"]["value"]
                finding["title"] = (record_data.get("title") or {}).get("value")
        token = sha256(json.dumps({"source": source, "exclude_id": str(exclude_id), "policy": result["policy"], "findings": findings},
                                 sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        rejected = any(f["action"] == "reject" for f in findings)
        needs_confirmation = any(f["action"] == "confirm" for f in findings) and confirmation != token
        if rejected or needs_confirmation:
            error = LibraryError("Duplicate references require review before saving.", details={
                "duplicates": findings, "confirmation_token": None if rejected else token,
            })
            error.code = "duplicate_reference" if rejected else "duplicate_confirmation_required"
            error.status_code = 409
            raise error
        return findings

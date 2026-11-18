"""Build persisted Japanese and English search aliases in the backend."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import logging
from threading import Event, Thread
from typing import Any
import unicodedata
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .db_models import ReferenceRecord, ReferenceSearchTranslation
from .search import mark_search_change
from .translation import Translator, translation_text


_LOGGER = logging.getLogger(__name__)
_BATCH_SIZE = 16
_POLL_SECONDS = 5
_LOCK_ID = 0x4269624D67525472
_LANGUAGES = {
    "ja": "ja", "jpn": "ja", "japanese": "ja", "日本語": "ja",
    "en": "en", "eng": "en", "english": "en", "英語": "en",
    "american": "en", "british": "en", "usenglish": "en", "ukenglish": "en",
}


def _fields(data: dict[str, Any]) -> dict[str, str]:
    fields = {}
    for field in data.get("extra_fields", []):
        value = (field.get("value") or {}).get("resolved")
        name = field.get("name")
        if isinstance(name, str) and isinstance(value, str) and value.strip():
            fields[name.casefold()] = value.strip()
    return fields


def _language(text: str) -> str | None:
    names = {unicodedata.name(character, "").split(" ", 1)[0] for character in text if character.isalpha()}
    if names & {"HIRAGANA", "KATAKANA", "CJK", "HALFWIDTH"}:
        return "ja"
    if names and names <= {"LATIN", "FULLWIDTH"}:
        return "en"
    return None


def _translate(translator: Translator, text: str | None, language: str | None) -> str:
    if not text or len(text) > 1024 or language is None:
        return ""
    return translation_text(translator.translate(text, language, "en" if language == "ja" else "ja"))


class TranslationWorker:
    def __init__(self, sessions: Callable[[], Session], translator: Translator) -> None:
        self._sessions = sessions
        self._translator = translator
        self._stop = Event()

    @contextmanager
    def running(self) -> Iterator[None]:
        thread = Thread(target=self._run, name="bibmgr-search-translation", daemon=True)
        thread.start()
        try:
            yield
        finally:
            self._stop.set()
            self._translator.close()
            thread.join(timeout=2)

    @contextmanager
    def _lease(self) -> Iterator[Callable[[], None] | None]:
        # Hold a session-level lock on a separate autocommit connection. Model
        # inference never holds a database transaction or a reference row lock.
        with self._sessions() as session:
            engine = session.get_bind()
        if engine.dialect.name != "postgresql":
            yield lambda: None
            return
        with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as lease:
            acquired = bool(lease.scalar(select(func.pg_try_advisory_lock(_LOCK_ID))))

            def check_connection() -> None:
                lease.execute(select(1))

            try:
                yield check_connection if acquired else None
            finally:
                if acquired and not lease.invalidated:
                    try:
                        lease.execute(select(func.pg_advisory_unlock(_LOCK_ID)))
                    except Exception:
                        lease.invalidate()

    def _run(self) -> None:
        # Each pass visits every eligible ID, even if a translation fails, and
        # retries failed entries on a later pass. Restarting resumes from the DB.
        while not self._stop.is_set():
            try:
                with self._lease() as check_connection:
                    if check_connection is not None:
                        self._run_passes(check_connection)
            except Exception as error:
                if not self._stop.is_set():
                    _LOGGER.warning("Search translation worker paused (%s)", type(error).__name__)
            self._stop.wait(_POLL_SECONDS)

    def _run_passes(self, check_connection: Callable[[], None]) -> None:
        while not self._stop.is_set():
            cursor = None
            while not self._stop.is_set():
                check_connection()
                count, cursor = self.process_batch(cursor, check_connection=check_connection)
                if count < _BATCH_SIZE:
                    break
            self._stop.wait(_POLL_SECONDS)

    def process_batch(
        self, after: UUID | None = None, *, check_connection: Callable[[], None] = lambda: None,
    ) -> tuple[int, UUID | None]:
        reference = ReferenceRecord
        translation = ReferenceSearchTranslation
        identity = self._translator.identity
        statement = (
            select(reference.id, reference.source_revision, reference.title, reference.semantic_data)
            .outerjoin(translation, translation.reference_id == reference.id)
            .where(or_(
                translation.reference_id.is_(None),
                translation.source_revision != reference.source_revision,
                translation.provider != identity.provider,
                translation.model != identity.model,
                translation.model_revision != identity.revision,
            ))
            .order_by(reference.id)
            .limit(_BATCH_SIZE)
        )
        if after is not None:
            statement = statement.where(reference.id > after)
        with self._sessions() as session:
            rows = session.execute(statement).all()

        for reference_id, revision, title, data in rows:
            if self._stop.is_set():
                break
            try:
                fields = _fields(data)
                language_tag = fields.get("langid") or fields.get("language")
                declared = _LANGUAGES.get(language_tag.casefold().replace("_", "-").split("-", 1)[0]) if language_tag else None
                keywords = fields.get("keywords")
                if language_tag and declared is None:
                    translated_title, translated_keywords = "", ""
                else:
                    translated_title = _translate(self._translator, title, declared or _language(title or ""))
                    translated_keywords = _translate(self._translator, keywords, _language(keywords or ""))
            except Exception as error:
                if not self._stop.is_set():
                    _LOGGER.warning("Search translation failed for %s (%s)", reference_id, type(error).__name__)
                    self._stop.wait(1)
                continue
            if not self._stop.is_set():
                check_connection()
                self._store(reference_id, revision, translated_title, translated_keywords)
        return len(rows), rows[-1].id if rows else after

    def _store(self, reference_id: UUID, revision: str, title: str, keywords: str) -> None:
        identity = self._translator.identity
        with self._sessions() as session, session.begin():
            current_revision = session.scalar(
                select(ReferenceRecord.source_revision).where(ReferenceRecord.id == reference_id).with_for_update()
            )
            if current_revision != revision:
                return
            record = session.get(ReferenceSearchTranslation, reference_id)
            if record is None:
                record = ReferenceSearchTranslation(reference_id=reference_id)
                session.add(record)
            changed = (
                record.source_revision, record.translated_title, record.translated_keywords
            ) != (revision, title, keywords)
            record.source_revision = revision
            record.provider = identity.provider
            record.model = identity.model
            record.model_revision = identity.revision
            record.translated_title = title
            record.translated_keywords = keywords
            if changed:
                mark_search_change(session, reference_id)

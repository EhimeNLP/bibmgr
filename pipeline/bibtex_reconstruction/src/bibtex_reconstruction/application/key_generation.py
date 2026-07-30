"""Deterministic citation-key generation with constrained concept ranking."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Protocol, Sequence

import bibmgr_native

from ..clients.llm import (
    LLMProvider,
    LLMProviderError,
    create_preferred_llm_providers,
)
from ..config import settings
from ..domain import (
    CitationKeyAudit,
    ConceptRankingResponse,
    ProcessedReference,
)
from ..domain.enums import ReconstructionOutcome, ReconstructionPath
from ..validation import NativeBibtexValidator


logger = logging.getLogger(__name__)

_TITLE_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "using",
    "via",
    "with",
    "approach",
    "analysis",
    "evaluation",
    "framework",
    "method",
    "model",
    "models",
    "new",
    "study",
    "system",
}
_VENUE_STOP_WORDS = {
    "annual",
    "conference",
    "international",
    "journal",
    "of",
    "on",
    "proceedings",
    "the",
    "transactions",
}


class ConceptRanker(Protocol):
    """Rank only candidates that were derived deterministically from titles."""

    def rank(
        self,
        requests: Sequence["ConceptRequest"],
    ) -> tuple[dict[str, list[int]], dict[str, str]]:
        """Return candidate indices and the method used per reference."""


@dataclass(frozen=True)
class ConceptRequest:
    ref_id: str
    title: str
    candidates: tuple[str, ...]


class ConfiguredConceptRanker:
    """Prefer local vLLM, then opt-in remote LLM, then rule order."""

    def __init__(
        self,
        providers: Sequence[LLMProvider] | None = None,
        *,
        batch_size: int | None = None,
    ) -> None:
        self.providers = list(
            providers
            if providers is not None
            else create_preferred_llm_providers()
        )
        self.batch_size = batch_size or settings.concept_ranking_batch_size

    def rank(
        self,
        requests: Sequence[ConceptRequest],
    ) -> tuple[dict[str, list[int]], dict[str, str]]:
        if not requests:
            return {}, {}
        rankings: dict[str, list[int]] = {}
        methods: dict[str, str] = {}
        for start in range(0, len(requests), self.batch_size):
            batch = requests[start:start + self.batch_size]
            prompt = self._prompt(batch)
            for provider in self.providers:
                label = getattr(
                    provider,
                    "provider_label",
                    "api_llm",
                )
                try:
                    response = provider.generate(
                        prompt,
                        ConceptRankingResponse,
                    )
                except LLMProviderError as exc:
                    logger.warning(
                        "concept ranker unavailable provider=%s reason=%s",
                        label,
                        exc,
                    )
                    continue
                normalized = self._normalize_response(response, batch)
                if normalized:
                    rankings.update(normalized)
                    methods.update(
                        {ref_id: label for ref_id in normalized}
                    )
                    break
        return rankings, methods

    @staticmethod
    def _prompt(requests: Sequence[ConceptRequest]) -> str:
        payload = [
            {
                "ref_id": request.ref_id,
                "title": request.title,
                "candidates": list(request.candidates),
            }
            for request in requests
        ]
        return (
            "Rank the supplied concept candidates for citation keys. "
            "Candidates were extracted from each paper title. Return candidate "
            "indices only, ordered from the most distinctive model, dataset, "
            "method, task, or technical concept to the least distinctive. Never "
            "add a candidate or modify candidate text. Include every ref_id. "
            "Return only the required JSON object.\n\n"
            f"INPUT:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )

    @staticmethod
    def _normalize_response(
        response: ConceptRankingResponse,
        requests: Sequence[ConceptRequest],
    ) -> dict[str, list[int]]:
        limits = {
            request.ref_id: len(request.candidates)
            for request in requests
        }
        result: dict[str, list[int]] = {}
        for ranking in response.rankings:
            limit = limits.get(ranking.ref_id)
            if limit is None:
                continue
            indices: list[int] = []
            for index in ranking.candidate_indices:
                if 0 <= index < limit and index not in indices:
                    indices.append(index)
            if indices:
                result[ranking.ref_id] = indices
        return result


@dataclass
class _PreparedKey:
    result: ProcessedReference
    source: str
    original_key: str
    key_range: tuple[int, int]
    surname: str
    year: str
    venue: str
    title: str
    candidates: tuple[str, ...]
    identity: str


class CitationKeyGenerator:
    """Rewrite only non-local citation-key CST ranges after reconstruction."""

    def __init__(
        self,
        *,
        ranker: ConceptRanker | None = None,
        validator: NativeBibtexValidator | None = None,
    ) -> None:
        self.ranker = ranker or ConfiguredConceptRanker()
        self.validator = validator or NativeBibtexValidator()

    def apply(self, results: Sequence[ProcessedReference]) -> None:
        """Mutate ready results with stable keys while preserving local DB source."""

        reserved: dict[str, str] = {}
        prepared: list[_PreparedKey] = []
        logger.info(
            "citation key generation started ready_count=%d",
            sum(
                result.outcome == ReconstructionOutcome.READY
                for result in results
            ),
        )
        for result in results:
            if (
                result.outcome != ReconstructionOutcome.READY
                or not result.reconstructed_bibtex
            ):
                continue
            if result.reconstruction_path == ReconstructionPath.LOCAL_DB:
                try:
                    original_key = _extract_original_key(
                        result.reconstructed_bibtex
                    )
                except (KeyError, StopIteration, TypeError, ValueError) as exc:
                    self._mark_review(
                        result,
                        f"local DB citation key inspection failed: {exc}",
                    )
                    continue
                normalized = original_key.casefold()
                reserved[normalized] = original_key
                result.citation_key = CitationKeyAudit(
                    original_citation_key=original_key,
                    generated_citation_key=original_key,
                    key_preserved=True,
                    concept_method="local_db",
                )
                logger.info(
                    "citation key preserved ref_id=%s path=local_db",
                    result.ref_id,
                )
                continue
            try:
                item = self._prepare(result)
            except (KeyError, StopIteration, TypeError, ValueError) as exc:
                self._mark_review(
                    result,
                    f"citation key generation failed: {exc}",
                )
                continue
            prepared.append(item)

        requests = [
            ConceptRequest(
                ref_id=item.result.ref_id,
                title=item.title,
                candidates=item.candidates,
            )
            for item in prepared
        ]
        rankings, methods = self.ranker.rank(requests)
        for item in sorted(prepared, key=lambda candidate: candidate.identity):
            item_method = methods.get(item.result.ref_id, "rule_based")
            indices = self._candidate_order(
                len(item.candidates),
                rankings.get(item.result.ref_id, []),
            )
            collisions: list[str] = []
            selected_index: int | None = None
            selected_key: str | None = None
            for index in indices:
                candidate_key = self._compose_key(item, item.candidates[index])
                conflict = reserved.get(candidate_key.casefold())
                if conflict is None:
                    selected_index = index
                    selected_key = candidate_key
                    break
                collisions.append(conflict)

            if selected_key is None:
                concept = item.candidates[indices[0]]
                base_key = self._compose_key(item, concept)
                suffix = hashlib.sha256(
                    item.identity.encode("utf-8")
                ).hexdigest()[:4]
                selected_key = f"{base_key}-{suffix}"
                selected_index = indices[0]
                while selected_key.casefold() in reserved:
                    suffix = hashlib.sha256(
                        f"{item.identity}:{suffix}".encode("utf-8")
                    ).hexdigest()[:6]
                    selected_key = f"{base_key}-{suffix}"

            try:
                rewritten = self._replace_key(item, selected_key)
                validation = self.validator.validate(rewritten)
            except (RuntimeError, TypeError, ValueError) as exc:
                self._mark_review(
                    item.result,
                    f"citation key edit failed: {exc}",
                )
                continue
            if not validation.accepted:
                self._mark_review(
                    item.result,
                    "generated citation key did not pass Rust validation",
                )
                continue

            reserved[selected_key.casefold()] = selected_key
            selected_concept = item.candidates[selected_index]
            item.result.reconstructed_bibtex = rewritten
            item.result.validation = validation.model_copy(
                update={"source": rewritten}
            )
            item.result.citation_key = CitationKeyAudit(
                original_citation_key=item.original_key,
                generated_citation_key=selected_key,
                surname=item.surname,
                year=item.year,
                venue=item.venue,
                concept=selected_concept,
                concept_candidates=list(item.candidates),
                selected_candidate_rank=indices.index(selected_index) + 1,
                concept_method=item_method,
                collision_keys=collisions,
            )
            logger.info(
                (
                    "citation key generated ref_id=%s method=%s "
                    "collision_count=%d"
                ),
                item.result.ref_id,
                item_method,
                len(collisions),
            )
        logger.info(
            "citation key generation completed generated_count=%d",
            sum(result.citation_key is not None for result in results),
        )

    @staticmethod
    def _prepare(result: ProcessedReference) -> _PreparedKey:
        source = result.reconstructed_bibtex
        if not source:
            raise ValueError("missing reconstructed BibTeX")
        analysis = bibmgr_native.analyze(
            source,
            profile="modern",
            tolerant=False,
        )
        bibliography = analysis.bibliography
        records = bibliography.get("records", [])
        if len(records) != 1:
            raise ValueError("expected exactly one semantic record")
        record = records[0]
        key_data = record["citation_key"]
        original_key = str(key_data["value"])
        key_origin = next(
            origin
            for origin in key_data["origins"]
            if origin.get("kind") == "citation_key"
        )
        key_range = key_origin["range"]

        authors = record.get("authors") or record.get("editors") or []
        if not authors:
            raise ValueError("author or editor is required for a laboratory key")
        person = authors[0]["value"]
        family = person.get("family") or person.get("literal") or []
        if isinstance(family, str):
            family_text = family
        else:
            family_text = "-".join(str(part) for part in family)
        surname = _slug(family_text) or "ref"

        date = record.get("date", {}).get("value", {})
        year_value = date.get("year")
        if not isinstance(year_value, int):
            raise ValueError("year is required for a laboratory key")
        year = str(year_value)

        title = str(record.get("title", {}).get("value") or "").strip()
        candidates = concept_candidates(title)
        if not candidates:
            raise ValueError("title has no portable concept candidate")

        venue_value = record.get("venue", {}).get("value") or {}
        venue = _venue_slug(venue_value)
        identity = _record_identity(record, result.ref_id)
        return _PreparedKey(
            result=result,
            source=source,
            original_key=original_key,
            key_range=(int(key_range["start"]), int(key_range["end"])),
            surname=surname,
            year=year,
            venue=venue,
            title=title,
            candidates=candidates,
            identity=identity,
        )

    @staticmethod
    def _replace_key(item: _PreparedKey, replacement: str) -> str:
        session = bibmgr_native.DocumentSession(
            item.source,
            profile="modern",
            tolerant=False,
        )
        session.update(
            session.analysis.source_revision,
            bibmgr_native.TextEdit(
                item.key_range[0],
                item.key_range[1],
                replacement,
            ),
        )
        return session.source

    @staticmethod
    def _compose_key(item: _PreparedKey, concept: str) -> str:
        return "-".join(
            part
            for part in (item.surname, item.year, item.venue, concept)
            if part
        )

    @staticmethod
    def _candidate_order(length: int, ranked: Sequence[int]) -> list[int]:
        result = [
            index for index in ranked if 0 <= index < length
        ]
        result.extend(index for index in range(length) if index not in result)
        return result

    @staticmethod
    def _mark_review(result: ProcessedReference, reason: str) -> None:
        result.outcome = ReconstructionOutcome.MANUAL_REVIEW
        result.reconstructed_bibtex = None
        result.review_reason = reason


def concept_candidates(title: str, *, limit: int = 8) -> tuple[str, ...]:
    """Return distinct title-derived candidates in deterministic rule order."""

    candidates: list[str] = []

    def add(value: str) -> None:
        normalized = _slug(value)
        if (
            normalized
            and normalized not in _TITLE_STOP_WORDS
            and normalized not in candidates
        ):
            candidates.append(normalized)

    if ":" in title:
        prefix = title.split(":", 1)[0].strip()
        if 1 <= len(prefix.split()) <= 2:
            add(prefix)
    for acronym in re.findall(
        r"\b[A-Z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*\b",
        title,
    ):
        if sum(character.isupper() for character in acronym) >= 2:
            add(acronym)
    for token in re.findall(r"[A-Za-z][A-Za-z0-9-]*", title):
        add(token)
    return tuple(candidates[:limit])


def _slug(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode(
        "ascii",
        "ignore",
    ).decode("ascii")
    return "-".join(
        part
        for part in re.split(r"[^a-z0-9]+", ascii_value.casefold())
        if part
    )


def _venue_slug(value: dict[str, object]) -> str:
    short_name = value.get("short_name")
    if isinstance(short_name, str) and _slug(short_name):
        return _slug(short_name)
    raw = str(value.get("full_name") or value.get("raw") or "")
    explicit_acronyms = re.findall(r"\b[A-Z][A-Z0-9-]{1,}\b", raw)
    if explicit_acronyms:
        return _slug(explicit_acronyms[0])
    acronym = "".join(
        token[0]
        for token in re.findall(r"[A-Za-z][A-Za-z0-9]*", raw)
        if token.casefold() not in _VENUE_STOP_WORDS
    )
    return _slug(acronym or raw) or "unknown"


def _record_identity(record: dict[str, object], ref_id: str) -> str:
    identifiers = record.get("identifiers")
    if isinstance(identifiers, dict):
        for name in ("dois", "arxiv"):
            values = identifiers.get(name)
            if isinstance(values, list) and values:
                return f"{name}:{json.dumps(values[0], sort_keys=True)}"
    title = record.get("title")
    if isinstance(title, dict) and title.get("value"):
        return f"title:{str(title['value']).casefold()}:{ref_id}"
    return f"ref:{ref_id}"


def _extract_original_key(source: str) -> str:
    analysis = bibmgr_native.analyze(
        source,
        profile="modern",
        tolerant=False,
    )
    records = analysis.bibliography.get("records", [])
    if len(records) != 1:
        raise ValueError("expected exactly one semantic record")
    return str(records[0]["citation_key"]["value"])

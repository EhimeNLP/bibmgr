"""Deterministic citation-key parts plus rule-guided LLM concept generation."""

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
    ConceptGenerationResponse,
    LLMInvocationAudit,
    ProcessedReference,
)
from ..domain.enums import LLMTask, ReconstructionOutcome, ReconstructionPath
from ..validation import NativeBibtexValidator


logger = logging.getLogger(__name__)

_RECOVERABLE_KEY_ERRORS = (
    AttributeError,
    IndexError,
    KeyError,
    RuntimeError,
    StopIteration,
    TypeError,
    ValueError,
)
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
    "exploring",
    "framework",
    "introduction",
    "method",
    "model",
    "models",
    "new",
    "overview",
    "rethinking",
    "review",
    "revisiting",
    "study",
    "survey",
    "system",
    "toward",
    "towards",
    "understanding",
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


class ConceptGenerator(Protocol):
    """Generate only the concept portion of a citation key."""

    def generate(
        self,
        requests: Sequence["ConceptRequest"],
    ) -> dict[str, "GeneratedConcept"]:
        """Return validated concepts keyed by reference ID."""


@dataclass(frozen=True)
class ConceptRequest:
    ref_id: str
    title: str
    raw_text: str
    candidates: tuple[str, ...]
    source_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class GeneratedConcept:
    concept: str
    source_terms: tuple[str, ...]
    audit: LLMInvocationAudit


class ConfiguredConceptGenerator:
    """Prefer local vLLM, then opt-in remote LLM, then rule fallback."""

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
        self.batch_size = batch_size or settings.concept_generation_batch_size

    def generate(
        self,
        requests: Sequence[ConceptRequest],
    ) -> dict[str, GeneratedConcept]:
        if not requests:
            return {}
        generated: dict[str, GeneratedConcept] = {}
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
                        ConceptGenerationResponse,
                    )
                except LLMProviderError as exc:
                    logger.warning(
                        "concept ranker unavailable provider=%s reason=%s",
                        label,
                        exc,
                    )
                    continue
                normalized = self._normalize_response(
                    response,
                    batch,
                    prompt=prompt,
                    provider=provider,
                )
                if normalized:
                    generated.update(normalized)
                    break
        return generated

    @staticmethod
    def _prompt(requests: Sequence[ConceptRequest]) -> str:
        payload = [
            {
                "ref_id": request.ref_id,
                "title": request.title,
                "raw_citation": request.raw_text,
                "rule_terms": list(
                    request.source_terms or request.candidates
                ),
            }
            for request in requests
        ]
        return (
            "TASK\n"
            "Generate only the concept part of an academic citation key. "
            "Surname, year, and venue are already fixed.\n\n"
            "KNOWLEDGE USE\n"
            "Use the title and raw_citation to identify the paper. You may use "
            "your pretrained knowledge to recover the paper's canonical method, "
            "model, dataset, system, or task name even when that name is not "
            "written verbatim in the title. Prefer a well-known canonical name "
            "only when you recognize it confidently; do not fabricate one.\n\n"
            "SELECTION ORDER\n"
            "1. Prefer the paper's canonical proper name or acronym from your "
            "knowledge.\n"
            "2. Otherwise prefer an explicitly named method, model, dataset, "
            "system, or task in the input.\n"
            "3. If neither is reliable, choose the single most distinctive "
            "technical noun from the title.\n"
            "4. Avoid generic words such as method, model, framework, system, "
            "analysis, evaluation, approach, and study.\n\n"
            "OUTPUT RULES\n"
            "- concept: exactly one concise lowercase ASCII word using only "
            "a-z and 0-9\n"
            "- for non-English papers, translate or romanize the canonical "
            "concept into one recognizable ASCII word\n"
            "- no spaces, hyphens, or concatenated multi-word phrases\n"
            "- source_terms: exact rule_terms used as paper-identification clues\n"
            "- include every ref_id\n"
            "- return only the JSON object required by the schema\n\n"
            f"INPUT\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
        )

    @staticmethod
    def _normalize_response(
        response: ConceptGenerationResponse,
        requests: Sequence[ConceptRequest],
        *,
        prompt: str,
        provider: LLMProvider,
    ) -> dict[str, GeneratedConcept]:
        request_map = {request.ref_id: request for request in requests}
        result: dict[str, GeneratedConcept] = {}
        for item in response.concepts:
            request = request_map.get(item.ref_id)
            if request is None:
                continue
            concept = _normalize_concept(item.concept)
            source_terms = tuple(
                term.strip() for term in item.source_terms if term.strip()
            )
            grounded = {
                _grounding_identity(term)
                for term in (request.source_terms or request.candidates)
            }
            if (
                not concept
                or len(concept) > 32
                or not source_terms
                or any(
                    _grounding_identity(term) not in grounded
                    for term in source_terms
                )
            ):
                continue
            result[item.ref_id] = GeneratedConcept(
                concept=concept,
                source_terms=source_terms,
                audit=LLMInvocationAudit(
                    task=LLMTask.KEY_CONCEPT_GENERATION,
                    provider=getattr(provider, "provider_label", "api_llm"),
                    model=getattr(provider, "model", None),
                    prompt_sha256=hashlib.sha256(
                        prompt.encode("utf-8")
                    ).hexdigest(),
                    response=item.model_dump(mode="json"),
                ),
            )
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
    rule_concept: str | None
    identity: str


class CitationKeyGenerator:
    """Rewrite only non-local citation-key CST ranges after reconstruction."""

    def __init__(
        self,
        *,
        concept_generator: ConceptGenerator | None = None,
        validator: NativeBibtexValidator | None = None,
    ) -> None:
        self.concept_generator = (
            concept_generator or ConfiguredConceptGenerator()
        )
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
                except _RECOVERABLE_KEY_ERRORS as exc:
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
            except _RECOVERABLE_KEY_ERRORS as exc:
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
                raw_text=item.result.original_data.raw_text,
                candidates=item.candidates,
                source_terms=_concept_source_terms(
                    item.title,
                    item.candidates,
                ),
            )
            for item in prepared
            if item.rule_concept is None
        ]
        generated = self.concept_generator.generate(requests)
        for item in sorted(prepared, key=lambda candidate: candidate.identity):
            generated_concept = generated.get(item.result.ref_id)
            if (
                generated_concept is not None
                and not _is_concept_word(generated_concept.concept)
            ):
                generated_concept = None
            concepts = list(item.candidates)
            if (
                generated_concept is not None
                and generated_concept.concept not in concepts
            ):
                concepts.insert(0, generated_concept.concept)
            elif generated_concept is not None:
                concepts.remove(generated_concept.concept)
                concepts.insert(0, generated_concept.concept)
            collisions: list[str] = []
            selected_rank: int | None = None
            selected_key: str | None = None
            for rank, concept in enumerate(concepts, start=1):
                candidate_key = self._compose_key(item, concept)
                conflict = reserved.get(candidate_key.casefold())
                if conflict is None:
                    selected_rank = rank
                    selected_key = candidate_key
                    break
                collisions.append(conflict)

            if selected_key is None:
                concept = concepts[0]
                base_key = self._compose_key(item, concept)
                suffix = hashlib.sha256(
                    item.identity.encode("utf-8")
                ).hexdigest()[:4]
                selected_key = f"{base_key}-{suffix}"
                selected_rank = 1
                while selected_key.casefold() in reserved:
                    suffix = hashlib.sha256(
                        f"{item.identity}:{suffix}".encode("utf-8")
                    ).hexdigest()[:6]
                    selected_key = f"{base_key}-{suffix}"

            try:
                rewritten = self._replace_key(item, selected_key)
                validation = self.validator.validate(rewritten)
            except _RECOVERABLE_KEY_ERRORS as exc:
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
            selected_concept = concepts[selected_rank - 1]
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
                concept_candidates=concepts,
                concept_source_terms=(
                    list(generated_concept.source_terms)
                    if generated_concept is not None
                    else (
                        [item.rule_concept]
                        if item.rule_concept is not None
                        else []
                    )
                ),
                selected_candidate_rank=selected_rank,
                concept_method=(
                    generated_concept.audit.provider
                    if generated_concept is not None
                    else "rule_based"
                ),
                collision_keys=collisions,
                llm_invocation=(
                    generated_concept.audit
                    if generated_concept is not None
                    else None
                ),
            )
            logger.info(
                (
                    "citation key generated ref_id=%s method=%s "
                    "collision_count=%d"
                ),
                item.result.ref_id,
                (
                    generated_concept.audit.provider
                    if generated_concept is not None
                    else "rule_based"
                ),
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
        surname = _slug(family_text) or _stable_fallback(
            "author",
            family_text,
        )

        date = record.get("date", {}).get("value", {})
        year_value = date.get("year")
        if not isinstance(year_value, int):
            raise ValueError("year is required for a laboratory key")
        year = str(year_value)

        title = str(record.get("title", {}).get("value") or "").strip()
        candidates = concept_candidates(title)
        if not candidates:
            candidates = (_stable_fallback("work", title),)
        rule_concept = representative_concept(title)
        if rule_concept is not None:
            candidates = (
                rule_concept,
                *(item for item in candidates if item != rule_concept),
            )

        venue = record.get("venue") or {}
        venue_value = venue.get("value") or {}
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
            rule_concept=rule_concept,
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
    def _mark_review(result: ProcessedReference, reason: str) -> None:
        result.outcome = ReconstructionOutcome.MANUAL_REVIEW
        result.reconstructed_bibtex = None
        result.review_reason = reason


def concept_candidates(title: str, *, limit: int = 8) -> tuple[str, ...]:
    """Return distinct title-derived candidates in deterministic rule order."""

    candidates: list[str] = []

    def add(value: str) -> None:
        normalized = _candidate_word(value)
        if (
            normalized
            and normalized not in _TITLE_STOP_WORDS
            and normalized not in candidates
        ):
            candidates.append(normalized)

    if ":" in title:
        prefix = title.split(":", 1)[0].strip()
        if len(prefix.split()) == 1:
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


def representative_concept(title: str) -> str | None:
    """Return a high-confidence method/model name explicitly present in title."""

    if ":" in title:
        prefix = title.split(":", 1)[0].strip()
        candidate = _candidate_word(prefix)
        if (
            len(prefix.split()) == 1
            and candidate
            and candidate not in _TITLE_STOP_WORDS
        ):
            return candidate

    for token in re.findall(
        r"\b[A-Z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*\b",
        title,
    ):
        uppercase_count = sum(character.isupper() for character in token)
        if uppercase_count >= 2 or any(character.isdigit() for character in token):
            candidate = _candidate_word(token)
            if candidate and candidate not in _TITLE_STOP_WORDS:
                return candidate
    return None


def _candidate_word(value: str) -> str:
    return _slug(value).replace("-", "")


def _concept_source_terms(
    title: str,
    candidates: Sequence[str],
) -> tuple[str, ...]:
    """Return exact multilingual clues the model may cite as grounding."""

    terms = list(candidates)
    if title and any(ord(character) > 127 for character in title):
        terms.append(title.strip())
    return tuple(dict.fromkeys(term for term in terms if term))


def _grounding_identity(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold().strip()


def _stable_fallback(prefix: str, value: str) -> str:
    normalized = _grounding_identity(value) or prefix
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:8]
    return f"{prefix}{digest}"


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


def _normalize_concept(value: str) -> str:
    """Accept only one portable word as a concept."""

    normalized = _slug(value)
    return normalized if _is_concept_word(normalized) else ""


def _is_concept_word(value: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9]+", value))


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
    portable = _slug(acronym or raw)
    if portable:
        return portable
    return _stable_fallback("venue", raw) if raw else "unknown"


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

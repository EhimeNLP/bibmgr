"""High-accuracy BibTeX reconstruction orchestration."""

from __future__ import annotations

import concurrent.futures
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass

from ..clients import (
    ArxivClient,
    CiNiiClient,
    CrossrefClient,
    DoiContentNegotiationClient,
    JStageClient,
    OfficialCitationClient,
    SemanticScholarClient,
)
from ..clients.base import APIClientError
from ..config import settings
from ..domain import (
    CandidateResult,
    EvidenceBundle,
    InputData,
    LLMReconstruction,
    ProcessedReference,
    ReconstructionAttempt,
    RustValidationResult,
)
from ..domain.enums import (
    CandidateStatus,
    ReconstructionOutcome,
    ReconstructionPath,
)
from ..matching import calculate_similarity
from ..parsing.bibtex import (
    bibtex_fields,
    fill_missing_bibtex_fields,
    inspect_bibtex,
    metadata_bibtex_fields,
)
from ..parsing.identifiers import extract_dois, normalize_doi
from ..parsing.source_clues import enrich_search_clues
from ..validation import NativeBibtexValidator
from .semantic_reconstructor import (
    ConfiguredSemanticReconstructor,
    SemanticReconstructionUnavailable,
    SemanticReconstructor,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _EvaluatedCandidate:
    source: str
    validation: RustValidationResult
    path: ReconstructionPath
    quality_issues: tuple[str, ...]
    source_url: str | None = None

    @property
    def ready(self) -> bool:
        return self.validation.accepted and not self.quality_issues


class ReconstructionOrchestrator:
    """Coordinate deterministic DOI recovery, search, LLM repair, and Rust checks."""

    def __init__(
        self,
        *,
        external_clients: Sequence[object] | None = None,
        doi_client: DoiContentNegotiationClient | None = None,
        citation_client: OfficialCitationClient | None = None,
        validator: NativeBibtexValidator | None = None,
        reconstructor: SemanticReconstructor | None = None,
        search_workers: int | None = None,
    ) -> None:
        self.external_clients = list(external_clients) if external_clients is not None else [
            CrossrefClient(),
            SemanticScholarClient(),
            CiNiiClient(),
            JStageClient(),
            ArxivClient(),
        ]
        self.doi_client = doi_client or DoiContentNegotiationClient()
        self.citation_client = citation_client or OfficialCitationClient()
        self.validator = validator or NativeBibtexValidator()
        self.reconstructor = reconstructor or ConfiguredSemanticReconstructor()
        self.search_workers = search_workers or settings.api_threads

    def reconstruct_reference(self, input_data: InputData) -> ProcessedReference:
        """Reconstruct one reference without accepting unvalidated output."""

        original_input = input_data
        search_input = InputData(
            parsed_data=enrich_search_clues(input_data.parsed_data)
        )
        reference = original_input.parsed_data
        search_reference = search_input.parsed_data
        logger.info("reconstruction started ref_id=%s", reference.id)
        extracted_dois = extract_dois(
            reference.doi,
            search_reference.doi,
            reference.raw_text,
        )
        attempts: list[ReconstructionAttempt] = []
        last_candidate: str | None = None
        last_validation: RustValidationResult | None = None
        last_quality_issues: tuple[str, ...] = ()
        doi_evaluations: dict[str, _EvaluatedCandidate] = {}

        # Exact identifiers present in the input are the strongest evidence.
        for doi in extracted_dois:
            direct_result = self._try_doi_recovery(
                doi,
                attempts=attempts,
            )
            if direct_result is None:
                continue
            doi_evaluations[doi] = direct_result
            last_candidate = direct_result.source
            last_validation = direct_result.validation
            last_quality_issues = direct_result.quality_issues
            if direct_result.ready:
                evidence = self._build_evidence(
                    original_input,
                    search_input=search_input,
                    extracted_dois=extracted_dois,
                    trusted_doi=doi,
                    candidates=[],
                )
                return self._accepted_result(
                    original_input,
                    evidence=evidence,
                    path=direct_result.path,
                    validation=direct_result.validation,
                    attempts=attempts,
                )

        candidates = self._search_candidates(search_input)
        trusted_doi = self._select_trusted_doi(
            search_input,
            candidates,
            excluded=set(extracted_dois),
        )
        evidence = self._build_evidence(
            original_input,
            search_input=search_input,
            extracted_dois=extracted_dois,
            trusted_doi=trusted_doi or (extracted_dois[0] if extracted_dois else None),
            candidates=candidates,
        )

        # Search-discovered identifiers use the same staged DOI recovery.
        recovery_dois = list(
            dict.fromkeys(
                doi
                for doi in [trusted_doi, *extracted_dois]
                if doi
            )
        )
        for doi in recovery_dois:
            direct_result = doi_evaluations.get(doi)
            if direct_result is None:
                direct_result = self._try_doi_recovery(
                    doi,
                    attempts=attempts,
                )
            if direct_result is None:
                continue

            last_candidate = direct_result.source
            last_validation = direct_result.validation
            last_quality_issues = direct_result.quality_issues
            if not direct_result.ready:
                enriched = self._try_metadata_enrichment(
                    direct_result.source,
                    doi=doi,
                    candidates=candidates,
                    attempts=attempts,
                )
                if enriched is not None:
                    direct_result = enriched
                    last_candidate = enriched.source
                    last_validation = enriched.validation
                    last_quality_issues = enriched.quality_issues

            if direct_result.ready:
                return self._accepted_result(
                    original_input,
                    evidence=evidence,
                    path=direct_result.path,
                    validation=direct_result.validation,
                    attempts=attempts,
                )

        try:
            for _ in range(settings.max_llm_attempts):
                llm_result = self.reconstructor.reconstruct(
                    evidence,
                    previous_candidate=last_candidate,
                    validation=last_validation,
                    quality_issues=last_quality_issues,
                )
                produced_candidate = llm_result.bibtex.strip()
                evaluated = self._evaluate_candidate(
                    produced_candidate,
                    path=ReconstructionPath.LLM,
                    attempts=attempts,
                    llm_result=llm_result,
                )
                last_validation = evaluated.validation
                last_candidate = last_validation.source
                last_quality_issues = evaluated.quality_issues
                logger.info(
                    (
                        "LLM candidate checked ref_id=%s accepted=%s "
                        "complete=%s attempt=%d"
                    ),
                    reference.id,
                    last_validation.accepted,
                    evaluated.ready,
                    len(attempts),
                )
                if evaluated.ready:
                    return self._accepted_result(
                        original_input,
                        evidence=evidence,
                        path=ReconstructionPath.LLM,
                        validation=last_validation,
                        attempts=attempts,
                    )
        except SemanticReconstructionUnavailable as exc:
            logger.warning(
                "semantic reconstruction unavailable ref_id=%s reason=%s",
                reference.id,
                exc,
            )
            return self._review_result(
                input_data,
                evidence=evidence,
                candidates=candidates,
                validation=last_validation,
                attempts=attempts,
                reason=str(exc),
            )
        except Exception:
            logger.exception("semantic reconstruction failed ref_id=%s", reference.id)
            return self._review_result(
                input_data,
                evidence=evidence,
                candidates=candidates,
                validation=last_validation,
                attempts=attempts,
                reason="semantic reconstruction failed",
            )

        return self._review_result(
            input_data,
            evidence=evidence,
            candidates=candidates,
            validation=last_validation,
            attempts=attempts,
            reason=(
                "Rust validation or core metadata quality did not pass after "
                f"{settings.max_llm_attempts} LLM attempts"
            ),
        )

    def _search_candidates(self, input_data: InputData) -> list[CandidateResult]:
        clients = self.external_clients
        if not clients:
            return []

        max_workers = min(len(clients), self.search_workers)
        candidates: list[CandidateResult] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_client = {
                executor.submit(client.search, input_data): client
                for client in clients
            }
            for future in concurrent.futures.as_completed(future_to_client):
                client = future_to_client[future]
                api_name = getattr(client, "api_name", client.__class__.__name__)
                try:
                    metadata, bibtex = future.result()
                    if metadata is None:
                        logger.info(
                            "API search completed ref_id=%s api=%s status=%s",
                            input_data.parsed_data.id,
                            api_name,
                            CandidateStatus.NOT_FOUND.value,
                        )
                        candidates.append(
                            CandidateResult(
                                source_api=api_name,
                                status=CandidateStatus.NOT_FOUND,
                            )
                        )
                        continue

                    score = self._candidate_score(input_data, metadata)
                    status = (
                        CandidateStatus.MATCH
                        if score >= settings.similarity_threshold
                        else CandidateStatus.WEAK_MATCH
                    )
                    logger.info(
                        (
                            "API search completed ref_id=%s api=%s "
                            "status=%s score=%.3f"
                        ),
                        input_data.parsed_data.id,
                        api_name,
                        status.value,
                        score,
                    )
                    candidates.append(
                        CandidateResult(
                            source_api=api_name,
                            status=status,
                            confidence_score=score,
                            verified_info=metadata,
                            bibtex=bibtex,
                        )
                    )
                except APIClientError as exc:
                    logger.warning(
                        "search failed ref_id=%s api=%s %s",
                        input_data.parsed_data.id,
                        api_name,
                        exc.safe_summary,
                    )
                    candidates.append(
                        CandidateResult(
                            source_api=api_name,
                            status=CandidateStatus.API_ERROR,
                            error=exc.safe_summary,
                        )
                    )
                except Exception as exc:
                    logger.warning(
                        "search failed ref_id=%s api=%s error_type=%s",
                        input_data.parsed_data.id,
                        api_name,
                        exc.__class__.__name__,
                    )
                    candidates.append(
                        CandidateResult(
                            source_api=api_name,
                            status=CandidateStatus.API_ERROR,
                            error=exc.__class__.__name__,
                        )
                    )

        return sorted(
            candidates,
            key=lambda candidate: candidate.confidence_score or 0.0,
            reverse=True,
        )

    def _candidate_score(self, input_data: InputData, metadata: object) -> float:
        reference = input_data.parsed_data
        metadata_doi = normalize_doi(getattr(metadata, "doi", None))
        input_dois = extract_dois(reference.doi, reference.raw_text)
        if metadata_doi and metadata_doi in input_dois:
            return 1.0
        return calculate_similarity(
            reference.title or "",
            getattr(metadata, "title", "") or "",
        )

    def _select_trusted_doi(
        self,
        input_data: InputData,
        candidates: Sequence[CandidateResult],
        *,
        excluded: set[str] | None = None,
    ) -> str | None:
        excluded = excluded or set()
        reference = input_data.parsed_data
        for candidate in candidates:
            metadata = candidate.verified_info
            if (
                metadata is None
                or not metadata.doi
                or (candidate.confidence_score or 0.0) < settings.trusted_doi_threshold
            ):
                continue
            doi = normalize_doi(metadata.doi)
            if not doi or doi in excluded:
                continue
            if (
                reference.comparison_year
                and metadata.year
                and reference.comparison_year != metadata.year
            ):
                continue
            if not self._authors_are_consistent(
                reference.authors,
                metadata.authors,
            ):
                continue
            logger.info(
                "trusted DOI selected ref_id=%s api=%s doi=%s",
                reference.id,
                candidate.source_api,
                doi,
            )
            return doi
        return None

    @staticmethod
    def _authors_are_consistent(
        original_authors: Sequence[str],
        candidate_authors: Sequence[str],
    ) -> bool:
        if not original_authors:
            return True
        if not candidate_authors:
            return False

        def tokens(authors: Sequence[str]) -> set[str]:
            return {
                token
                for author in authors
                for token in re.findall(r"[\w]+", author.casefold())
                if len(token) > 1
            }

        original_tokens = tokens(original_authors)
        candidate_tokens = tokens(candidate_authors)
        return bool(original_tokens and original_tokens & candidate_tokens)

    def _try_doi_recovery(
        self,
        doi: str,
        *,
        attempts: list[ReconstructionAttempt],
    ) -> _EvaluatedCandidate | None:
        """Try DOI metadata, then an official citation export if incomplete."""

        doi_result = self._try_doi_candidate(doi, attempts=attempts)
        if doi_result is not None and doi_result.ready:
            return doi_result

        citation_result = self._try_official_citation(
            doi,
            attempts=attempts,
        )
        if citation_result is not None:
            if citation_result.ready:
                return citation_result
            if (
                doi_result is None
                or len(citation_result.quality_issues)
                < len(doi_result.quality_issues)
            ):
                return citation_result
        return doi_result

    def _try_doi_candidate(
        self,
        doi: str,
        *,
        attempts: list[ReconstructionAttempt],
    ) -> _EvaluatedCandidate | None:
        try:
            candidate = self.doi_client.fetch_bibtex(doi)
        except Exception as exc:
            logger.warning(
                "DOI BibTeX retrieval failed doi=%s error_type=%s",
                doi,
                exc.__class__.__name__,
            )
            return None
        if not candidate:
            return None

        evaluated = self._evaluate_candidate(
            candidate,
            path=ReconstructionPath.DOI_CONTENT_NEGOTIATION,
            attempts=attempts,
        )
        logger.info(
            "DOI candidate checked doi=%s accepted=%s complete=%s missing=%s",
            doi,
            evaluated.validation.accepted,
            evaluated.ready,
            ",".join(evaluated.quality_issues) or "none",
        )
        return evaluated

    def _try_official_citation(
        self,
        doi: str,
        *,
        attempts: list[ReconstructionAttempt],
    ) -> _EvaluatedCandidate | None:
        try:
            citation = self.citation_client.fetch_bibtex(doi)
        except Exception as exc:
            logger.warning(
                "official citation retrieval failed doi=%s error_type=%s",
                doi,
                exc.__class__.__name__,
            )
            return None
        if citation is None:
            return None

        evaluated = self._evaluate_candidate(
            citation.bibtex,
            path=ReconstructionPath.OFFICIAL_CITATION,
            attempts=attempts,
            source_url=citation.source_url,
        )
        logger.info(
            (
                "official citation checked doi=%s accepted=%s "
                "complete=%s missing=%s"
            ),
            doi,
            evaluated.validation.accepted,
            evaluated.ready,
            ",".join(evaluated.quality_issues) or "none",
        )
        return evaluated

    def _try_metadata_enrichment(
        self,
        source: str,
        *,
        doi: str,
        candidates: Sequence[CandidateResult],
        attempts: list[ReconstructionAttempt],
    ) -> _EvaluatedCandidate | None:
        inspection = inspect_bibtex(source)
        field_sources: list[dict[str, str | None]] = []
        for candidate in candidates:
            metadata = candidate.verified_info
            if (
                candidate.status != CandidateStatus.MATCH
                or metadata is None
                or normalize_doi(metadata.doi) != doi
            ):
                continue
            field_sources.append(
                metadata_bibtex_fields(
                    entry_type=inspection.entry_type,
                    title=metadata.title,
                    authors=metadata.authors,
                    year=metadata.year,
                    venue=metadata.venue,
                    doi=metadata.doi,
                    url=metadata.url,
                )
            )
            fields = bibtex_fields(candidate.bibtex or "")
            field_sources.append(
                self._compatible_candidate_fields(
                    fields,
                    entry_type=inspection.entry_type,
                )
            )

        enriched, filled_fields = fill_missing_bibtex_fields(
            source,
            field_sources,
        )
        if not filled_fields:
            return None
        evaluated = self._evaluate_candidate(
            enriched,
            path=ReconstructionPath.METADATA_ENRICHMENT,
            attempts=attempts,
            filled_fields=filled_fields,
        )
        logger.info(
            (
                "metadata-enriched candidate checked doi=%s accepted=%s "
                "complete=%s filled=%s missing=%s"
            ),
            doi,
            evaluated.validation.accepted,
            evaluated.ready,
            ",".join(filled_fields),
            ",".join(evaluated.quality_issues) or "none",
        )
        return evaluated

    @staticmethod
    def _compatible_candidate_fields(
        fields: dict[str, str],
        *,
        entry_type: str | None,
    ) -> dict[str, str]:
        result = dict(fields)
        if entry_type == "article":
            result.pop("booktitle", None)
        elif entry_type in {
            "conference",
            "inbook",
            "incollection",
            "inproceedings",
        }:
            result.pop("journal", None)
        else:
            result.pop("booktitle", None)
            result.pop("journal", None)
        return result

    def _evaluate_candidate(
        self,
        source: str,
        *,
        path: ReconstructionPath,
        attempts: list[ReconstructionAttempt],
        source_url: str | None = None,
        filled_fields: Sequence[str] = (),
        llm_result: LLMReconstruction | None = None,
    ) -> _EvaluatedCandidate:
        validation = self.validator.validate(source)
        inspection = inspect_bibtex(validation.source)
        quality_issues = inspection.missing_fields
        attempts.append(
            ReconstructionAttempt(
                attempt=len(attempts) + 1,
                path=path,
                candidate_bibtex=source,
                validation=validation,
                source_url=source_url,
                quality_issues=list(quality_issues),
                filled_fields=list(filled_fields),
                llm_result=llm_result,
            )
        )
        return _EvaluatedCandidate(
            source=validation.source,
            validation=validation,
            path=path,
            quality_issues=quality_issues,
            source_url=source_url,
        )

    @staticmethod
    def _build_evidence(
        input_data: InputData,
        *,
        search_input: InputData,
        extracted_dois: list[str],
        trusted_doi: str | None,
        candidates: list[CandidateResult],
    ) -> EvidenceBundle:
        reference = input_data.parsed_data
        return EvidenceBundle(
            raw_text=reference.raw_text,
            original=reference,
            search_clues=search_input.parsed_data,
            extracted_dois=extracted_dois,
            trusted_doi=trusted_doi,
            candidates=candidates,
        )

    @staticmethod
    def _accepted_result(
        input_data: InputData,
        *,
        evidence: EvidenceBundle,
        path: ReconstructionPath,
        validation: RustValidationResult,
        attempts: list[ReconstructionAttempt],
    ) -> ProcessedReference:
        return ProcessedReference(
            ref_id=input_data.parsed_data.id,
            outcome=ReconstructionOutcome.READY,
            original_data=input_data.parsed_data,
            candidates=evidence.candidates,
            evidence=evidence,
            reconstruction_path=path,
            reconstructed_bibtex=validation.source,
            validation=validation,
            attempts=attempts,
        )

    @staticmethod
    def _review_result(
        input_data: InputData,
        *,
        evidence: EvidenceBundle,
        candidates: list[CandidateResult],
        validation: RustValidationResult | None,
        attempts: list[ReconstructionAttempt],
        reason: str,
    ) -> ProcessedReference:
        return ProcessedReference(
            ref_id=input_data.parsed_data.id,
            outcome=ReconstructionOutcome.MANUAL_REVIEW,
            original_data=input_data.parsed_data,
            candidates=candidates,
            evidence=evidence,
            validation=validation,
            attempts=attempts,
            review_reason=reason,
        )

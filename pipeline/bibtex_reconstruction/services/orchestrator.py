"""High-accuracy BibTeX reconstruction orchestration."""

from __future__ import annotations

import concurrent.futures
import logging
import re
from collections.abc import Sequence

from api_clients import (
    ArxivClient,
    CiNiiClient,
    CrossrefClient,
    DoiContentNegotiationClient,
    JStageClient,
    SemanticScholarClient,
)
from core import calculate_similarity, settings
from core.constants import CandidateStatus, ReconstructionOutcome, ReconstructionPath
from core.identifiers import extract_dois, normalize_doi
from core.native_validation import NativeBibtexValidator
from core.source_clues import enrich_search_clues
from models import (
    CandidateResult,
    EvidenceBundle,
    InputData,
    LLMReconstruction,
    ProcessedReference,
    ReconstructionAttempt,
    RustValidationResult,
)
from services.semantic_reconstructor import (
    ConfiguredSemanticReconstructor,
    SemanticReconstructionUnavailable,
    SemanticReconstructor,
)


logger = logging.getLogger(__name__)


class ReconstructionOrchestrator:
    """Coordinate deterministic DOI recovery, search, LLM repair, and Rust checks."""

    def __init__(
        self,
        *,
        external_clients: Sequence[object] | None = None,
        doi_client: DoiContentNegotiationClient | None = None,
        validator: NativeBibtexValidator | None = None,
        reconstructor: SemanticReconstructor | None = None,
    ) -> None:
        self.external_clients = list(external_clients) if external_clients is not None else [
            CrossrefClient(),
            SemanticScholarClient(),
            CiNiiClient(),
            JStageClient(),
            ArxivClient(),
        ]
        self.doi_client = doi_client or DoiContentNegotiationClient()
        self.validator = validator or NativeBibtexValidator(
            policy=settings.registration_policy
        )
        self.reconstructor = reconstructor or ConfiguredSemanticReconstructor()

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

        # Exact identifiers present in the input are the strongest evidence.
        for doi in extracted_dois:
            direct_result = self._try_doi_candidate(
                doi,
                attempts=attempts,
            )
            if direct_result is None:
                continue
            last_candidate, last_validation = direct_result
            if last_validation.accepted:
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
                    path=ReconstructionPath.DOI_CONTENT_NEGOTIATION,
                    validation=last_validation,
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

        # A high-confidence DOI returned by search also bypasses the LLM.
        if trusted_doi:
            direct_result = self._try_doi_candidate(
                trusted_doi,
                attempts=attempts,
            )
            if direct_result is not None:
                last_candidate, last_validation = direct_result
                if last_validation.accepted:
                    return self._accepted_result(
                        original_input,
                        evidence=evidence,
                        path=ReconstructionPath.DOI_CONTENT_NEGOTIATION,
                        validation=last_validation,
                        attempts=attempts,
                    )

        try:
            for _ in range(settings.max_llm_attempts):
                llm_result = self.reconstructor.reconstruct(
                    evidence,
                    previous_candidate=last_candidate,
                    validation=last_validation,
                )
                produced_candidate = llm_result.bibtex.strip()
                last_validation = self.validator.validate(produced_candidate)
                attempts.append(
                    ReconstructionAttempt(
                        attempt=len(attempts) + 1,
                        path=ReconstructionPath.LLM,
                        candidate_bibtex=produced_candidate,
                        validation=last_validation,
                        llm_result=llm_result,
                    )
                )
                last_candidate = last_validation.source
                logger.info(
                    "LLM candidate checked ref_id=%s accepted=%s attempt=%d",
                    reference.id,
                    last_validation.accepted,
                    len(attempts),
                )
                if last_validation.accepted:
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
            reason=f"Rust validation did not pass after {settings.max_llm_attempts} LLM attempts",
        )

    def _search_candidates(self, input_data: InputData) -> list[CandidateResult]:
        clients = self.external_clients
        if not clients:
            return []

        max_workers = min(len(clients), settings.max_parallel_requests)
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
                    candidates.append(
                        CandidateResult(
                            source_api=api_name,
                            status=status,
                            confidence_score=score,
                            verified_info=metadata,
                            bibtex=bibtex,
                        )
                    )
                except Exception as exc:
                    logger.warning("search failed api=%s error=%s", api_name, exc)
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
                reference.year
                and metadata.year
                and str(reference.year) != str(metadata.year)
            ):
                continue
            if not self._authors_are_consistent(
                reference.authors,
                metadata.authors,
            ):
                continue
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

    def _try_doi_candidate(
        self,
        doi: str,
        *,
        attempts: list[ReconstructionAttempt],
    ) -> tuple[str, RustValidationResult] | None:
        try:
            candidate = self.doi_client.fetch_bibtex(doi)
        except Exception as exc:
            logger.warning("DOI BibTeX retrieval failed doi=%s error=%s", doi, exc)
            return None
        if not candidate:
            return None

        validation = self.validator.validate(candidate)
        attempts.append(
            ReconstructionAttempt(
                attempt=len(attempts) + 1,
                path=ReconstructionPath.DOI_CONTENT_NEGOTIATION,
                candidate_bibtex=candidate,
                validation=validation,
            )
        )
        logger.info("DOI candidate checked doi=%s accepted=%s", doi, validation.accepted)
        return validation.source, validation

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

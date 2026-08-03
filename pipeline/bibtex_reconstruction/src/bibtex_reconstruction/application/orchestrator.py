"""High-accuracy, source-preserving BibTeX reconstruction orchestration."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..clients import (
    AclAnthologyClient,
    ArxivClient,
    CiNiiClient,
    CrossrefClient,
    DoiContentNegotiationClient,
    JStageClient,
    LocalDBClient,
    OfficialCitationClient,
    SemanticScholarClient,
)
from ..clients.base import APIClientError
from ..config import settings
from ..domain import (
    BibtexEvidence,
    CandidateResult,
    DoiEvidenceGroup,
    EvidenceBundle,
    FieldConflict,
    FieldSupplement,
    InputData,
    ProcessedReference,
    QueryImprovementAudit,
    RejectedBibtexEvidence,
    ReconstructionAttempt,
    RustValidationResult,
    SelectionDecision,
)
from ..domain.enums import (
    BibtexSourceKind,
    CandidateStatus,
    ReconstructionOutcome,
    ReconstructionPath,
)
from ..matching import (
    calculate_author_similarity,
    calculate_citation_similarity,
    calculate_similarity,
)
from ..parsing.bibtex import (
    bibtex_fields,
    insert_missing_bibtex_fields,
    inspect_bibtex,
    metadata_bibtex_fields,
    replace_bibtex_citation_key,
)
from ..parsing.identifiers import extract_dois, normalize_doi
from ..parsing.source_clues import enrich_search_clues
from ..validation import NativeBibtexValidator
from .metadata_synthesis import synthesize_metadata_bibtex
from .query_improvement import ConfiguredQueryImprover, QueryImprover


logger = logging.getLogger(__name__)

_SOURCE_PRIORITIES = {
    "BibMgR Local DB": 0,
    "ACL Anthology": 10,
    "Crossref API": 20,
    "Semantic Scholar API": 30,
    "CiNii API": 40,
    "J-STAGE API": 50,
    "arXiv API": 90,
}


@dataclass(frozen=True)
class _SelectedSource:
    bibtex: str
    path: ReconstructionPath
    decision: SelectionDecision
    source_url: str | None = None
    quality_issues: tuple[str, ...] = ()
    filled_fields: tuple[str, ...] = ()


class ReconstructionOrchestrator:
    """Keep evidence independent and select one deterministic base source."""

    def __init__(
        self,
        *,
        external_clients: Sequence[object] | None = None,
        doi_client: DoiContentNegotiationClient | None = None,
        citation_client: OfficialCitationClient | None = None,
        validator: NativeBibtexValidator | None = None,
        query_improver: QueryImprover | None = None,
        local_db_client: LocalDBClient | None = None,
        search_workers: int | None = None,
    ) -> None:
        self.external_clients = (
            list(external_clients)
            if external_clients is not None
            else [
                AclAnthologyClient(),
                CrossrefClient(),
                SemanticScholarClient(),
                CiNiiClient(),
                JStageClient(),
                ArxivClient(),
            ]
        )
        self.doi_client = doi_client or DoiContentNegotiationClient()
        self.citation_client = citation_client or OfficialCitationClient()
        self.validator = validator or NativeBibtexValidator()
        self.query_improver = query_improver or ConfiguredQueryImprover()
        self.local_db_client = local_db_client or LocalDBClient()
        self.search_workers = search_workers or settings.api_threads

    def reconstruct_reference(self, input_data: InputData) -> ProcessedReference:
        original = input_data.parsed_data
        search_reference = enrich_search_clues(original)
        search_input = InputData(parsed_data=search_reference)
        extracted_dois = extract_dois(
            original.doi,
            search_reference.doi,
            original.raw_text,
        )
        attempts: list[ReconstructionAttempt] = []
        query_audits: list[QueryImprovementAudit] = []

        local = self._try_local(search_input)
        if local is not None:
            metadata, bibtex = local
            candidate = self._candidate(
                source_api=self.local_db_client.api_name,
                status=CandidateStatus.MATCH,
                metadata=metadata,
                bibtex=bibtex,
                direct=True,
                authoritative=True,
                query=search_reference.title,
                query_round=0,
                confidence=1.0,
            )
            evidence = self._evidence(
                input_data,
                search_input,
                extracted_dois,
                normalize_doi(metadata.doi),
            )
            selected = _SelectedSource(
                bibtex=bibtex,
                path=ReconstructionPath.LOCAL_DB,
                decision=SelectionDecision(
                    source_kind=BibtexSourceKind.LOCAL_DB,
                    candidate_id=candidate.candidate_id,
                    doi=normalize_doi(metadata.doi),
                    reason="exact existing local-library entry",
                ),
            )
            return self._finalize(
                input_data,
                evidence=evidence,
                selected=selected,
                attempts=attempts,
                query_audits=query_audits,
                candidates=[candidate],
                doi_groups=[],
            )

        # An identifier extracted from the input is stronger than any fuzzy
        # provider search. Fetch both DOI representations first and avoid API
        # search entirely when they already yield a complete source.
        input_doi_groups = [
            self._collect_doi_evidence(search_input, doi, [])
            for doi in extracted_dois
        ]
        for group in input_doi_groups:
            selections = self._doi_group_selections(
                search_input,
                group,
                [],
            )
            if any(
                not option.quality_issues
                and not option.decision.conflicts
                for option in selections
            ):
                evidence = self._evidence(
                    input_data,
                    search_input,
                    extracted_dois,
                    group.doi,
                )
                return self._finalize(
                    input_data,
                    evidence=evidence,
                    selected=selections[0],
                    fallbacks=selections[1:],
                    attempts=attempts,
                    query_audits=query_audits,
                    candidates=[],
                    doi_groups=input_doi_groups,
                )

        candidates = self._search_candidates(search_input, query_round=0)
        if (
            settings.query_improvement_enabled
            and settings.query_improvement_max_rounds > 0
            and not self._deterministic_search_succeeded(
                search_input,
                candidates,
            )
        ):
            attempted_queries = {
                self._query_identity(search_reference.title or "")
            }
            improvement_reference = search_reference
            for query_round in range(
                1,
                settings.query_improvement_max_rounds + 1,
            ):
                audit = self.query_improver.improve(
                    improvement_reference
                ).model_copy(update={"query_round": query_round})
                query_audits.append(audit)
                round_queries: list[str] = []
                for query in self._prioritized_queries(audit.queries):
                    identity = self._query_identity(query)
                    if not identity or identity in attempted_queries:
                        continue
                    attempted_queries.add(identity)
                    round_queries.append(query)

                if not round_queries:
                    break
                for query in round_queries:
                    improved = search_reference.model_copy(
                        update={"title": query}
                    )
                    candidates.extend(
                        self._search_candidates(
                            InputData(parsed_data=improved),
                            query_round=query_round,
                            comparison_input=search_input,
                        )
                    )
                    if self._deterministic_search_succeeded(
                        search_input,
                        candidates,
                    ):
                        break
                candidates = self._sort_candidates(candidates)
                if self._deterministic_search_succeeded(
                    search_input,
                    candidates,
                ):
                    break
                improvement_reference = search_reference.model_copy(
                    update={"title": round_queries[0]}
                )

        trusted_dois = list(extracted_dois)
        for candidate in candidates:
            doi = self._trusted_candidate_doi(search_input, candidate)
            if doi and doi not in trusted_dois:
                trusted_dois.append(doi)

        input_groups = {group.doi: group for group in input_doi_groups}
        doi_groups = []
        for doi in trusted_dois:
            group = input_groups.get(doi)
            if group is None:
                group = self._collect_doi_evidence(
                    search_input,
                    doi,
                    candidates,
                )
            else:
                group = group.model_copy(
                    update={
                        "candidate_ids": [
                            candidate.candidate_id
                            for candidate in candidates
                            if candidate.discovered_doi == doi
                        ]
                    }
                )
            doi_groups.append(group)
        evidence = self._evidence(
            input_data,
            search_input,
            extracted_dois,
            trusted_dois[0] if trusted_dois else None,
        )

        selections: list[_SelectedSource] = []
        for group in doi_groups:
            selections.extend(
                self._doi_group_selections(
                    search_input,
                    group,
                    candidates,
                )
            )
        for fallback in (
            self._select_direct_api_export(
                search_input,
                candidates,
                excluded_sources={"arXiv API"},
            ),
            self._select_metadata_synthesis(search_input, candidates),
            self._select_direct_api_export(
                search_input,
                candidates,
                allowed_sources={"arXiv API"},
                allow_year_mismatch=True,
                require_strong_authors=True,
            ),
        ):
            if fallback is not None and all(
                option.bibtex != fallback.bibtex for option in selections
            ):
                selections.append(fallback)
        if not selections:
            return self._review(
                input_data,
                evidence=evidence,
                attempts=attempts,
                query_audits=query_audits,
                candidates=candidates,
                doi_groups=doi_groups,
                reason=(
                    "trusted deterministic sources did not produce a "
                    "complete BibTeX entry"
                ),
            )
        return self._finalize(
            input_data,
            evidence=evidence,
            selected=selections[0],
            fallbacks=selections[1:],
            attempts=attempts,
            query_audits=query_audits,
            candidates=candidates,
            doi_groups=doi_groups,
        )

    def _try_local(
        self,
        input_data: InputData,
    ) -> tuple[object, str] | None:
        if not settings.localdb_enabled:
            return None
        try:
            metadata, bibtex = self.local_db_client.search(input_data)
        except Exception as exc:
            logger.warning(
                "local DB lookup failed ref_id=%s error_type=%s",
                input_data.parsed_data.id,
                exc.__class__.__name__,
            )
            return None
        if metadata is None or not bibtex:
            return None
        return metadata, bibtex

    def _search_candidates(
        self,
        input_data: InputData,
        *,
        query_round: int,
        comparison_input: InputData | None = None,
    ) -> list[CandidateResult]:
        clients = list(self.external_clients)
        if ArxivClient.explicit_arxiv_id(input_data):
            clients = [
                client
                for client in clients
                if getattr(client, "api_name", "") == "arXiv API"
            ]
        if not clients:
            return []
        candidates: list[CandidateResult] = []
        max_workers = min(len(clients), self.search_workers)
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max_workers
        ) as executor:
            futures = {
                executor.submit(client.search, input_data): client
                for client in clients
            }
            for future in concurrent.futures.as_completed(futures):
                client = futures[future]
                api_name = getattr(
                    client,
                    "api_name",
                    client.__class__.__name__,
                )
                try:
                    metadata, bibtex = future.result()
                    if metadata is None:
                        candidates.append(
                            self._candidate(
                                source_api=api_name,
                                status=CandidateStatus.NOT_FOUND,
                                query=input_data.parsed_data.title,
                                query_round=query_round,
                            )
                        )
                        continue
                    score = self._candidate_score(
                        comparison_input or input_data,
                        metadata,
                    )
                    status = (
                        CandidateStatus.MATCH
                        if score >= settings.similarity_threshold
                        else CandidateStatus.WEAK_MATCH
                    )
                    candidates.append(
                        self._candidate(
                            source_api=api_name,
                            status=status,
                            metadata=metadata,
                            bibtex=bibtex,
                            direct=bool(
                                getattr(
                                    client,
                                    "direct_bibtex_eligible",
                                    getattr(
                                        client,
                                        "authoritative_bibtex",
                                        False,
                                    ),
                                )
                            ),
                            authoritative=bool(
                                getattr(
                                    client,
                                    "authoritative_bibtex",
                                    False,
                                )
                            ),
                            query=input_data.parsed_data.title,
                            query_round=query_round,
                            confidence=score,
                        )
                    )
                except APIClientError as exc:
                    candidates.append(
                        self._candidate(
                            source_api=api_name,
                            status=CandidateStatus.API_ERROR,
                            query=input_data.parsed_data.title,
                            query_round=query_round,
                            error=exc.safe_summary,
                        )
                    )
                except Exception as exc:
                    candidates.append(
                        self._candidate(
                            source_api=api_name,
                            status=CandidateStatus.API_ERROR,
                            query=input_data.parsed_data.title,
                            query_round=query_round,
                            error=exc.__class__.__name__,
                        )
                    )
        return self._sort_candidates(candidates)

    @staticmethod
    def _prioritized_queries(queries: Sequence[str]) -> list[str]:
        """Try explicit persistent identifiers before fuzzy text queries."""

        return sorted(
            queries,
            key=lambda query: (
                0
                if re.search(
                    r"(?:arxiv\s*:|arxiv\.org/(?:abs|pdf)/)",
                    query,
                    flags=re.IGNORECASE,
                )
                else 1
            ),
        )

    @staticmethod
    def _query_identity(query: str) -> str:
        """Normalize a query only for detecting repeated searches."""

        return " ".join(query.split()).casefold()

    @staticmethod
    def _candidate(
        *,
        source_api: str,
        status: CandidateStatus,
        metadata: object | None = None,
        bibtex: str | None = None,
        direct: bool = False,
        authoritative: bool = False,
        query: str | None = None,
        query_round: int = 0,
        confidence: float = 0.0,
        error: str | None = None,
    ) -> CandidateResult:
        doi = normalize_doi(getattr(metadata, "doi", None))
        identity = json.dumps(
            {
                "api": source_api,
                "round": query_round,
                "query": query,
                "doi": doi,
                "title": getattr(metadata, "title", None),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return CandidateResult(
            candidate_id=hashlib.sha256(
                identity.encode("utf-8")
            ).hexdigest()[:16],
            source_api=source_api,
            source_priority=_SOURCE_PRIORITIES.get(source_api, 70),
            status=status,
            confidence_score=confidence,
            verified_info=metadata,
            discovered_doi=doi,
            bibtex=bibtex,
            bibtex_direct=direct,
            bibtex_authoritative=authoritative,
            search_query=query,
            query_round=query_round,
            error=error,
        )

    @staticmethod
    def _sort_candidates(
        candidates: Sequence[CandidateResult],
    ) -> list[CandidateResult]:
        return sorted(
            candidates,
            key=lambda item: (
                item.source_priority,
                -(item.confidence_score or 0.0),
                item.source_api,
                item.candidate_id,
            ),
        )

    def _candidate_score(self, input_data: InputData, metadata: object) -> float:
        reference = input_data.parsed_data
        doi = normalize_doi(getattr(metadata, "doi", None))
        if doi and doi in extract_dois(reference.doi, reference.raw_text):
            return 1.0
        titles = [
            getattr(metadata, "title", "") or "",
            *(getattr(metadata, "alternative_titles", ()) or ()),
        ]
        author_groups = [
            getattr(metadata, "authors", ()) or (),
            *(getattr(metadata, "alternative_authors", ()) or ()),
        ]
        return max(
            calculate_citation_similarity(
                reference.title or "",
                title,
                original_authors=reference.authors,
                found_authors=authors,
            )
            for title in titles
            for authors in author_groups
        )

    def _deterministic_search_succeeded(
        self,
        input_data: InputData,
        candidates: Sequence[CandidateResult],
    ) -> bool:
        """Return true only when search produced an actually usable result."""

        trusted_doi_found = any(
            self._trusted_candidate_doi(input_data, candidate)
            for candidate in candidates
        )
        return any(
            selection is not None
            for selection in (
                self._select_direct_api_export(
                    input_data,
                    candidates,
                    excluded_sources={"arXiv API"},
                ),
                self._select_metadata_synthesis(input_data, candidates),
                self._select_direct_api_export(
                    input_data,
                    candidates,
                    allowed_sources={"arXiv API"},
                    allow_year_mismatch=True,
                    require_strong_authors=True,
                ),
            )
        ) or trusted_doi_found

    def _trusted_candidate_doi(
        self,
        input_data: InputData,
        candidate: CandidateResult,
    ) -> str | None:
        metadata = candidate.verified_info
        doi = candidate.discovered_doi
        if (
            candidate.status != CandidateStatus.MATCH
            or metadata is None
            or not doi
            or (candidate.confidence_score or 0.0)
            < settings.trusted_doi_threshold
        ):
            return None
        if not self._candidate_metadata_is_consistent(
            input_data,
            candidate,
        ):
            return None
        return doi

    @staticmethod
    def _authors_are_consistent(
        original_authors: Sequence[str],
        candidate_authors: Sequence[str],
    ) -> bool:
        if not original_authors:
            return True
        if not candidate_authors:
            return False
        return calculate_author_similarity(
            original_authors,
            candidate_authors,
        ) > 0.0

    def _collect_doi_evidence(
        self,
        input_data: InputData,
        doi: str,
        candidates: Sequence[CandidateResult],
    ) -> DoiEvidenceGroup:
        official: BibtexEvidence | None = None
        negotiated: BibtexEvidence | None = None
        rejected: list[RejectedBibtexEvidence] = []
        try:
            citation = self.citation_client.fetch_bibtex(doi)
        except Exception as exc:
            logger.warning(
                "official citation retrieval failed doi=%s error_type=%s",
                doi,
                exc.__class__.__name__,
            )
        else:
            if citation is not None:
                official, rejection = self._bibtex_evidence(
                    input_data,
                    citation.bibtex,
                    source_kind=BibtexSourceKind.OFFICIAL_CITATION,
                    doi=doi,
                    source_url=citation.source_url,
                )
                if rejection is not None:
                    rejected.append(rejection)
        try:
            source = self.doi_client.fetch_bibtex(doi)
        except Exception as exc:
            logger.warning(
                "DOI BibTeX retrieval failed doi=%s error_type=%s",
                doi,
                exc.__class__.__name__,
            )
        else:
            if source:
                negotiated, rejection = self._bibtex_evidence(
                    input_data,
                    source,
                    source_kind=(
                        BibtexSourceKind.DOI_CONTENT_NEGOTIATION
                    ),
                    doi=doi,
                )
                if rejection is not None:
                    rejected.append(rejection)
        return DoiEvidenceGroup(
            doi=doi,
            candidate_ids=[
                candidate.candidate_id
                for candidate in candidates
                if candidate.discovered_doi == doi
            ],
            official_citation=official,
            content_negotiation=negotiated,
            rejected_evidence=rejected,
        )

    @classmethod
    def _bibtex_evidence(
        cls,
        input_data: InputData,
        bibtex: str,
        *,
        source_kind: BibtexSourceKind,
        doi: str,
        source_url: str | None = None,
    ) -> tuple[BibtexEvidence | None, RejectedBibtexEvidence | None]:
        fields = bibtex_fields(bibtex)
        observed_doi = normalize_doi(fields.get("doi"))
        reason: str | None = None
        if observed_doi and observed_doi != doi:
            reason = "BibTeX DOI does not match the requested DOI"
        elif not observed_doi:
            reference = input_data.parsed_data
            title = fields.get("title", "")
            authors = cls._bibtex_authors(fields.get("author", ""))
            title_matches = calculate_similarity(
                reference.title or "",
                title,
            ) >= settings.trusted_doi_threshold
            authors_match = cls._authors_are_consistent(
                reference.authors,
                authors,
            )
            if not title_matches or not authors_match:
                reason = (
                    "DOI-less BibTeX does not match the input title and authors"
                )
        if reason is not None:
            return None, RejectedBibtexEvidence(
                source_kind=source_kind,
                bibtex=bibtex,
                reason=reason,
                requested_doi=doi,
                observed_doi=observed_doi,
                source_url=source_url,
            )
        return BibtexEvidence(
            source_kind=source_kind,
            bibtex=bibtex,
            doi=doi,
            source_url=source_url,
            quality_issues=list(inspect_bibtex(bibtex).missing_fields),
        ), None

    @staticmethod
    def _bibtex_authors(value: str) -> list[str]:
        return [
            author.strip()
            for author in re.split(r"\s+and\s+", value, flags=re.IGNORECASE)
            if author.strip()
        ]

    def _select_from_doi_group(
        self,
        group: DoiEvidenceGroup,
        candidates: Sequence[CandidateResult],
        *,
        prefer_official: bool = True,
    ) -> _SelectedSource | None:
        official = group.official_citation
        negotiated = group.content_negotiation
        base = (official or negotiated) if prefer_official else negotiated
        if base is None:
            return None
        base_inspection = inspect_bibtex(base.bibtex)
        if not base_inspection.parsed:
            if base is official and negotiated is not None:
                base = negotiated
                base_inspection = inspect_bibtex(base.bibtex)
            if not base_inspection.parsed:
                return None

        supplement_fields: Mapping[str, str | None] | None = None
        supplement_kind: BibtexSourceKind | None = None
        supplement_api: str | None = None
        supplement_candidate_id: str | None = None
        if base_inspection.missing_fields:
            if base is official and negotiated is not None:
                supplement_fields = bibtex_fields(negotiated.bibtex)
                supplement_kind = (
                    BibtexSourceKind.DOI_CONTENT_NEGOTIATION
                )
                supplement_api = "DOI Content Negotiation"
            if supplement_fields is None:
                supplement = next(
                    (
                        candidate
                        for candidate in candidates
                        if candidate.status == CandidateStatus.MATCH
                        and candidate.discovered_doi == group.doi
                        and candidate.source_api != "arXiv API"
                    ),
                    None,
                )
                if supplement is not None:
                    supplement_fields = self._candidate_fields(
                        supplement,
                        entry_type=base_inspection.entry_type,
                    )
                    supplement_kind = BibtexSourceKind.API_EXPORT
                    supplement_api = supplement.source_api
                    supplement_candidate_id = supplement.candidate_id

        final_source = base.bibtex
        filled: list[str] = []
        supplements: list[FieldSupplement] = []
        conflicts: list[FieldConflict] = []
        if supplement_fields and supplement_kind and supplement_api:
            conflicts = self._conflicts(base.bibtex, supplement_fields)
            final_source, filled = insert_missing_bibtex_fields(
                base.bibtex,
                supplement_fields,
            )
            supplements = [
                FieldSupplement(
                    field=name,
                    value=str(supplement_fields[name]),
                    source_kind=supplement_kind,
                    source_api=supplement_api,
                    candidate_id=supplement_candidate_id,
                    doi=group.doi,
                )
                for name in filled
            ]
        quality = inspect_bibtex(final_source).missing_fields
        path = (
            ReconstructionPath.METADATA_ENRICHMENT
            if filled
            else (
                ReconstructionPath.OFFICIAL_CITATION
                if base.source_kind
                == BibtexSourceKind.OFFICIAL_CITATION
                else ReconstructionPath.DOI_CONTENT_NEGOTIATION
            )
        )
        return _SelectedSource(
            bibtex=final_source,
            path=path,
            source_url=base.source_url,
            quality_issues=quality,
            filled_fields=tuple(filled),
            decision=SelectionDecision(
                source_kind=base.source_kind,
                doi=group.doi,
                source_url=base.source_url,
                reason=(
                    "official DOI landing-page citation used as immutable base"
                    if base.source_kind
                    == BibtexSourceKind.OFFICIAL_CITATION
                    else "DOI content-negotiation representation selected"
                ),
                supplements=supplements,
                conflicts=conflicts,
            ),
        )

    def _doi_group_selections(
        self,
        input_data: InputData,
        group: DoiEvidenceGroup,
        candidates: Sequence[CandidateResult],
    ) -> list[_SelectedSource]:
        """Return independent same-DOI representations in trust order."""

        selections: list[_SelectedSource] = []
        primary = self._select_from_doi_group(group, candidates)
        if primary is not None:
            selections.append(primary)
        if group.official_citation and group.content_negotiation:
            negotiated = self._select_from_doi_group(
                group,
                candidates,
                prefer_official=False,
            )
            if negotiated is not None and all(
                item.bibtex != negotiated.bibtex for item in selections
            ):
                selections.append(negotiated)
        direct = self._select_direct_api_export(
            input_data,
            candidates,
            required_doi=group.doi,
            threshold=settings.trusted_doi_threshold,
        )
        if direct is not None and all(
            item.bibtex != direct.bibtex for item in selections
        ):
            selections.append(direct)
        return selections

    @staticmethod
    def _candidate_fields(
        candidate: CandidateResult,
        *,
        entry_type: str | None,
    ) -> dict[str, str | None]:
        fields = bibtex_fields(candidate.bibtex or "")
        metadata = candidate.verified_info
        if metadata is not None:
            for name, value in metadata_bibtex_fields(
                entry_type=entry_type,
                title=metadata.title,
                authors=metadata.authors,
                year=metadata.year,
                venue=metadata.venue,
                publisher=metadata.publisher,
                volume=metadata.volume,
                number=metadata.number,
                pages=metadata.pages,
                doi=metadata.doi,
                url=metadata.url,
            ).items():
                fields.setdefault(name, value)
        if entry_type == "article":
            fields.pop("booktitle", None)
        elif entry_type in {
            "conference",
            "inbook",
            "incollection",
            "inproceedings",
        }:
            fields.pop("journal", None)
        return fields

    @staticmethod
    def _conflicts(
        base_bibtex: str,
        supplement: Mapping[str, str | None],
    ) -> list[FieldConflict]:
        base = bibtex_fields(base_bibtex)
        conflicts: list[FieldConflict] = []
        for name in ("title", "year", "doi"):
            left = base.get(name)
            right = supplement.get(name)
            if not left or not right:
                continue
            normalize = lambda value: re.sub(
                r"[^a-z0-9]+",
                "",
                str(value).casefold(),
            )
            if normalize(left) != normalize(right):
                conflicts.append(
                    FieldConflict(
                        field=name,
                        values={"base": left, "supplement": str(right)},
                        reason=(
                            "same-DOI sources disagree; base value was "
                            "preserved and automatic acceptance is withheld"
                        ),
                    )
                )
        return conflicts

    def _select_direct_api_export(
        self,
        input_data: InputData,
        candidates: Sequence[CandidateResult],
        *,
        required_doi: str | None = None,
        threshold: float | None = None,
        allowed_sources: set[str] | None = None,
        excluded_sources: set[str] | None = None,
        allow_year_mismatch: bool = False,
        require_strong_authors: bool = True,
    ) -> _SelectedSource | None:
        minimum = (
            settings.direct_bibtex_threshold
            if threshold is None
            else threshold
        )
        for candidate in self._sort_candidates(candidates):
            if (
                candidate.status != CandidateStatus.MATCH
                or (candidate.confidence_score or 0.0) < minimum
                or not candidate.bibtex_direct
                or not candidate.bibtex
                or (
                    allowed_sources is not None
                    and candidate.source_api not in allowed_sources
                )
                or (
                    excluded_sources is not None
                    and candidate.source_api in excluded_sources
                )
                or (
                    required_doi is not None
                    and candidate.discovered_doi != required_doi
                )
                or not self._candidate_metadata_is_consistent(
                    input_data,
                    candidate,
                    allow_year_mismatch=allow_year_mismatch,
                    require_strong_authors=require_strong_authors,
                )
            ):
                continue
            inspection = inspect_bibtex(candidate.bibtex)
            if inspection.complete:
                observed: list[FieldConflict] = []
                metadata = candidate.verified_info
                reference_year = input_data.parsed_data.comparison_year
                if (
                    allow_year_mismatch
                    and metadata is not None
                    and reference_year
                    and metadata.year
                    and reference_year != metadata.year
                ):
                    values = {
                        "metadata_extraction": str(reference_year),
                        f"{candidate.source_api} metadata": str(
                            metadata.year
                        ),
                    }
                    bibtex_year = bibtex_fields(candidate.bibtex).get("year")
                    if bibtex_year:
                        values[f"{candidate.source_api} BibTeX"] = bibtex_year
                    observed.append(
                        FieldConflict(
                            field="year",
                            values=values,
                            reason=(
                                "year differences do not reject an otherwise "
                                "strong arXiv fallback; the official export "
                                "remains unchanged"
                            ),
                        )
                    )
                return _SelectedSource(
                    bibtex=candidate.bibtex,
                    path=ReconstructionPath.EXTERNAL_API,
                    source_url=metadata.url if metadata is not None else None,
                    quality_issues=inspection.missing_fields,
                    decision=SelectionDecision(
                        source_kind=BibtexSourceKind.API_EXPORT,
                        candidate_id=candidate.candidate_id,
                        doi=candidate.discovered_doi,
                        source_url=(
                            metadata.url if metadata is not None else None
                        ),
                        reason=(
                            "direct provider citation export selected after "
                            "higher-priority DOI sources were unavailable"
                        ),
                        observed_conflicts=observed,
                    ),
                )
        return None

    def _select_metadata_synthesis(
        self,
        input_data: InputData,
        candidates: Sequence[CandidateResult],
    ) -> _SelectedSource | None:
        """Create one entry from a single strongly matched typed candidate."""

        for candidate in self._sort_candidates(candidates):
            metadata = candidate.verified_info
            if (
                candidate.source_api == "arXiv API"
                or candidate.status != CandidateStatus.MATCH
                or (candidate.confidence_score or 0.0)
                < settings.direct_bibtex_threshold
                or metadata is None
                or not self._candidate_metadata_is_consistent(
                    input_data,
                    candidate,
                    allow_year_mismatch=True,
                    require_strong_authors=True,
                )
            ):
                continue
            synthesis = synthesize_metadata_bibtex(
                input_data.parsed_data,
                candidate,
            )
            if synthesis is None:
                continue
            inspection = inspect_bibtex(synthesis.bibtex)
            if not inspection.complete:
                continue
            return _SelectedSource(
                bibtex=synthesis.bibtex,
                path=ReconstructionPath.METADATA_SYNTHESIS,
                source_url=metadata.url,
                quality_issues=inspection.missing_fields,
                filled_fields=tuple(synthesis.fields),
                decision=SelectionDecision(
                    source_kind=BibtexSourceKind.METADATA_SYNTHESIS,
                    candidate_id=candidate.candidate_id,
                    doi=candidate.discovered_doi,
                    source_url=metadata.url,
                    reason=(
                        "complete BibTeX deterministically synthesized from "
                        "one strongly matched, explicitly typed candidate"
                    ),
                    observed_conflicts=list(
                        synthesis.observed_conflicts
                    ),
                    generated_entry_type=synthesis.entry_type,
                    field_provenance=list(synthesis.provenance),
                ),
            )
        return None

    def _candidate_metadata_is_consistent(
        self,
        input_data: InputData,
        candidate: CandidateResult,
        *,
        allow_year_mismatch: bool = False,
        require_strong_authors: bool = False,
    ) -> bool:
        metadata = candidate.verified_info
        if metadata is None:
            return False
        reference = input_data.parsed_data
        if (
            not allow_year_mismatch
            and reference.comparison_year
            and metadata.year
            and reference.comparison_year != metadata.year
        ):
            return False
        return any(
            (
                not reference.authors
                or (
                    bool(authors)
                    and calculate_author_similarity(
                        reference.authors,
                        authors,
                    )
                    >= (0.50 if require_strong_authors else 0.000001)
                )
            )
            for authors in (
                metadata.authors,
                *metadata.alternative_authors,
            )
        )

    def _finalize(
        self,
        input_data: InputData,
        *,
        evidence: EvidenceBundle,
        selected: _SelectedSource,
        attempts: list[ReconstructionAttempt],
        query_audits: list[QueryImprovementAudit],
        candidates: list[CandidateResult],
        doi_groups: list[DoiEvidenceGroup],
        fallbacks: Sequence[_SelectedSource] = (),
    ) -> ProcessedReference:
        last_selected = selected
        last_validation: RustValidationResult | None = None
        last_quality: tuple[str, ...] = ()
        for option in (selected, *fallbacks):
            for variant in self._validation_variants(option):
                validation = self.validator.validate(variant.bibtex)
                quality = (
                    ()
                    if variant.path == ReconstructionPath.LOCAL_DB
                    else inspect_bibtex(variant.bibtex).missing_fields
                )
                attempts.append(
                    ReconstructionAttempt(
                        attempt=len(attempts) + 1,
                        path=variant.path,
                        candidate_bibtex=variant.bibtex,
                        validation=validation,
                        source_url=variant.source_url,
                        quality_issues=list(quality),
                        filled_fields=list(variant.filled_fields),
                    )
                )
                last_selected = variant
                last_validation = validation
                last_quality = quality
                conflict = bool(variant.decision.conflicts)
                if validation.accepted and not quality and not conflict:
                    return ProcessedReference(
                        ref_id=input_data.parsed_data.id,
                        outcome=ReconstructionOutcome.READY,
                        original_data=input_data.parsed_data,
                        candidates=candidates,
                        evidence=evidence,
                        reconstruction_path=variant.path,
                        reconstructed_bibtex=variant.bibtex,
                        validation=validation.model_copy(
                            update={"source": variant.bibtex}
                        ),
                        attempts=attempts,
                        query_improvements=query_audits,
                        doi_groups=doi_groups,
                        selection=variant.decision,
                    )
                if conflict:
                    break
            if last_selected.decision.conflicts:
                break

        reasons = ["all eligible BibTeX representations were exhausted"]
        if last_validation is not None and not last_validation.accepted:
            reasons.append("final Rust validation rejected the last source")
        if last_quality:
            reasons.append(
                "required fields remain missing: "
                + ", ".join(last_quality)
            )
        if last_selected.decision.conflicts:
            reasons.append("same-DOI evidence contains field conflicts")
        return self._review(
            input_data,
            evidence=evidence,
            attempts=attempts,
            query_audits=query_audits,
            candidates=candidates,
            doi_groups=doi_groups,
            reason="; ".join(reasons),
            validation=last_validation,
            selection=last_selected.decision,
        )

    @staticmethod
    def _validation_variants(
        selected: _SelectedSource,
    ) -> list[_SelectedSource]:
        """Try the provider source, then a field-preserving safe-key variant."""

        variants = [selected]
        if selected.path == ReconstructionPath.LOCAL_DB:
            return variants
        inspection = inspect_bibtex(selected.bibtex)
        key = inspection.citation_key or ""
        replacement = re.sub(r"[^A-Za-z0-9_.:+-]+", "-", key).strip("-")
        if not replacement:
            replacement = "reconstructed"
        if not key or replacement == key:
            return variants
        repaired = replace_bibtex_citation_key(
            selected.bibtex,
            replacement,
        )
        if repaired == selected.bibtex:
            return variants
        variants.append(
            _SelectedSource(
                bibtex=repaired,
                path=selected.path,
                decision=selected.decision.model_copy(
                    update={
                        "reason": (
                            selected.decision.reason
                            + "; provider citation key made parser-safe"
                        )
                    }
                ),
                source_url=selected.source_url,
                quality_issues=selected.quality_issues,
                filled_fields=selected.filled_fields,
            )
        )
        return variants

    @staticmethod
    def _evidence(
        input_data: InputData,
        search_input: InputData,
        extracted_dois: list[str],
        trusted_doi: str | None,
    ) -> EvidenceBundle:
        return EvidenceBundle(
            raw_text=input_data.parsed_data.raw_text,
            original=input_data.parsed_data,
            search_clues=search_input.parsed_data,
            extracted_dois=extracted_dois,
            trusted_doi=trusted_doi,
        )

    @staticmethod
    def _review(
        input_data: InputData,
        *,
        evidence: EvidenceBundle,
        attempts: list[ReconstructionAttempt],
        query_audits: list[QueryImprovementAudit],
        reason: str,
        candidates: list[CandidateResult],
        doi_groups: list[DoiEvidenceGroup],
        validation: RustValidationResult | None = None,
        selection: SelectionDecision | None = None,
    ) -> ProcessedReference:
        return ProcessedReference(
            ref_id=input_data.parsed_data.id,
            outcome=ReconstructionOutcome.MANUAL_REVIEW,
            original_data=input_data.parsed_data,
            candidates=candidates,
            evidence=evidence,
            validation=validation,
            attempts=attempts,
            query_improvements=query_audits,
            doi_groups=doi_groups,
            selection=selection,
            review_reason=reason,
        )

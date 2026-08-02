"""Reconstruction results and replayable audit-report contracts."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import (
    BibtexSourceKind,
    CandidateStatus,
    LLMTask,
    ReconstructionOutcome,
    ReconstructionPath,
)
from .input import DocumentMetadata, ReferenceData


class VerifiedCitationInfo(BaseModel):
    """Normalized metadata plus the untouched provider payload."""

    title: str
    alternative_titles: List[str] = Field(default_factory=list)
    authors: List[str] = Field(default_factory=list)
    alternative_authors: List[List[str]] = Field(default_factory=list)
    publication_types: List[str] = Field(default_factory=list)
    publication_date: Optional[str] = None
    year: Optional[int] = None
    venue: Optional[str] = None
    publisher: Optional[str] = None
    volume: Optional[str] = None
    number: Optional[str] = None
    pages: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None
    raw_payload: Any = None


class CandidateResult(BaseModel):
    """One provider result kept independent from every other provider."""

    candidate_id: str
    source_api: str = Field(..., description="The API that provided this candidate (e.g., 'Crossref', 'CiNii')")
    source_priority: int = Field(ge=0)
    status: CandidateStatus = Field(..., description="Search result classification for this API")
    confidence_score: Optional[float] = Field(0.0, ge=0.0, le=1.0, description="Similarity score calculated for this specific result (0.0 to 1.0)")
    verified_info: Optional[VerifiedCitationInfo] = Field(None, description="Verified metadata obtained from the API. None if not found.")
    discovered_doi: Optional[str] = None
    bibtex: Optional[str] = Field(None, description="Untouched BibTeX returned directly by this API")
    bibtex_direct: bool = Field(
        False,
        description=(
            "Provider-returned BibTeX eligible for validated selection"
        ),
    )
    bibtex_authoritative: bool = Field(
        False,
        description="Whether the provider owns the represented bibliography",
    )
    search_query: Optional[str] = None
    query_round: int = Field(0, ge=0)
    metadata_artifact_id: Optional[str] = None
    bibtex_artifact_id: Optional[str] = None
    error: Optional[str] = Field(None, description="Non-sensitive API failure summary")


class BibtexEvidence(BaseModel):
    """An exact BibTeX representation associated with one DOI or source."""

    source_kind: BibtexSourceKind
    bibtex: str
    doi: Optional[str] = None
    source_url: Optional[str] = None
    candidate_id: Optional[str] = None
    quality_issues: List[str] = Field(default_factory=list)
    artifact_id: Optional[str] = None


class DoiEvidenceGroup(BaseModel):
    """All exact evidence associated with one normalized DOI."""

    doi: str
    candidate_ids: List[str] = Field(default_factory=list)
    official_citation: Optional[BibtexEvidence] = None
    content_negotiation: Optional[BibtexEvidence] = None


class FieldSupplement(BaseModel):
    """One missing field inserted without overwriting the base source."""

    field: str
    value: str
    source_kind: BibtexSourceKind
    source_api: str
    candidate_id: Optional[str] = None
    doi: Optional[str] = None


class FieldConflict(BaseModel):
    """Conflicting values deliberately withheld from automatic merging."""

    field: str
    values: dict[str, str]
    reason: str


class FieldProvenance(BaseModel):
    """Origin of one field in a deterministically synthesized entry."""

    field: str
    value: str
    source_api: str
    source_attribute: str
    candidate_id: Optional[str] = None


class SelectionDecision(BaseModel):
    """Auditable choice of the single base representation."""

    source_kind: BibtexSourceKind
    reason: str
    doi: Optional[str] = None
    candidate_id: Optional[str] = None
    source_url: Optional[str] = None
    supplements: List[FieldSupplement] = Field(default_factory=list)
    conflicts: List[FieldConflict] = Field(default_factory=list)
    observed_conflicts: List[FieldConflict] = Field(default_factory=list)
    generated_entry_type: Optional[str] = None
    field_provenance: List[FieldProvenance] = Field(default_factory=list)


class EvidenceBundle(BaseModel):
    """Source-preserving evidence supplied to recovery and manual review."""

    raw_text: str
    original: ReferenceData
    search_clues: ReferenceData
    extracted_dois: List[str] = Field(default_factory=list)
    trusted_doi: Optional[str] = None


class ValidationDiagnostic(BaseModel):
    code: str
    severity: str
    blocking: bool
    message: str
    range: Optional[tuple[int, int]] = None
    notes: List[str] = Field(default_factory=list)
    fixes: List[str] = Field(default_factory=list)


class RustValidationResult(BaseModel):
    accepted: bool
    source: str
    unresolved_semantics: bool = False
    diagnostics: List[ValidationDiagnostic] = Field(default_factory=list)
    applied_fix_ids: List[str] = Field(default_factory=list)


class SearchQueryResponse(BaseModel):
    """Structured query suggestions; values never become bibliography facts."""

    queries: List[str] = Field(default_factory=list)


class LLMInvocationAudit(BaseModel):
    """Replay information for an authorized structured LLM call."""

    task: LLMTask
    provider: str
    model: Optional[str] = None
    prompt_sha256: str
    response: dict[str, Any]


class QueryImprovementAudit(BaseModel):
    """Queries generated after deterministic search was insufficient."""

    queries: List[str] = Field(default_factory=list)
    invocation: Optional[LLMInvocationAudit] = None


class ConceptGenerationItem(BaseModel):
    """One model-generated concept grounded by rule-derived hints."""

    ref_id: str
    concept: str = Field(
        min_length=1,
        max_length=32,
        pattern=r"^[a-z0-9]+$",
    )
    source_terms: List[str] = Field(default_factory=list)


class ConceptGenerationResponse(BaseModel):
    """Batch response for rule-guided key concept generation."""

    concepts: List[ConceptGenerationItem] = Field(default_factory=list)


class CitationKeyAudit(BaseModel):
    """Auditable details for one preserved or generated citation key."""

    original_citation_key: str
    generated_citation_key: str
    key_preserved: bool = False
    surname: Optional[str] = None
    year: Optional[str] = None
    venue: Optional[str] = None
    concept: Optional[str] = None
    concept_candidates: List[str] = Field(default_factory=list)
    concept_source_terms: List[str] = Field(default_factory=list)
    selected_candidate_rank: Optional[int] = Field(default=None, ge=1)
    concept_method: str
    collision_keys: List[str] = Field(default_factory=list)
    llm_invocation: Optional[LLMInvocationAudit] = None


class ReconstructionAttempt(BaseModel):
    attempt: int = Field(ge=1)
    path: ReconstructionPath
    candidate_bibtex: str
    validation: Optional[RustValidationResult] = None
    source_url: Optional[str] = None
    quality_issues: List[str] = Field(default_factory=list)
    filled_fields: List[str] = Field(default_factory=list)


class ProcessedReference(BaseModel):
    ref_id: str = Field(
        ...,
        description="Stable reference ID supplied by metadata_extraction",
    )
    outcome: ReconstructionOutcome
    original_data: ReferenceData = Field(
        ...,
        description="The extracted reference before clue enrichment",
    )
    candidates: List[CandidateResult] = Field(default_factory=list, description="List of all matching results from various APIs, sorted by score")
    evidence: Optional[EvidenceBundle] = None
    reconstruction_path: Optional[ReconstructionPath] = None
    reconstructed_bibtex: Optional[str] = None
    final_artifact_id: Optional[str] = None
    validation: Optional[RustValidationResult] = None
    attempts: List[ReconstructionAttempt] = Field(default_factory=list)
    query_improvements: List[QueryImprovementAudit] = Field(
        default_factory=list
    )
    doi_groups: List[DoiEvidenceGroup] = Field(default_factory=list)
    selection: Optional[SelectionDecision] = None
    citation_key: Optional[CitationKeyAudit] = None
    review_reason: Optional[str] = None


class ArtifactReference(BaseModel):
    """Content-addressed evidence stored beside the JSON manifest."""

    artifact_id: str
    relative_path: str
    media_type: str
    sha256: str
    byte_length: int = Field(ge=0)


class ReconstructionRun(BaseModel):
    """Runtime details needed to interpret and replay a report."""

    created_at: datetime
    code_revision: Optional[str] = None
    working_tree_dirty: Optional[bool] = None
    configuration: dict[str, Any] = Field(default_factory=dict)


class ReconstructionReport(BaseModel):
    """Typed audit report for one metadata_extraction document."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2"] = "2"
    run: ReconstructionRun
    input_path: Path
    input_artifact_id: str
    bibtex_output_path: Path
    artifact_directory: Path
    artifacts: List[ArtifactReference] = Field(default_factory=list)
    document: DocumentMetadata
    total_reference_count: int = Field(ge=0)
    reconstructed_count: int = Field(ge=0)
    manual_review_count: int = Field(ge=0)
    processed_references: List[ProcessedReference]

    @model_validator(mode="after")
    def validate_counts(self) -> ReconstructionReport:
        if self.total_reference_count != len(self.processed_references):
            raise ValueError(
                "total_reference_count must equal processed_references length"
            )
        reconstructed = sum(
            result.outcome == ReconstructionOutcome.READY
            for result in self.processed_references
        )
        manual_review = sum(
            result.outcome == ReconstructionOutcome.MANUAL_REVIEW
            for result in self.processed_references
        )
        if self.reconstructed_count != reconstructed:
            raise ValueError(
                "reconstructed_count does not match processed references"
            )
        if self.manual_review_count != manual_review:
            raise ValueError(
                "manual_review_count does not match processed references"
            )
        return self

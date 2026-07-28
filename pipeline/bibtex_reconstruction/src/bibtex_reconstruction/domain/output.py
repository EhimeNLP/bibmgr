"""Reconstruction results and audit-report contracts."""
from __future__ import annotations

from pathlib import Path
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import CandidateStatus, ReconstructionOutcome, ReconstructionPath
from .input import DocumentMetadata, ReferenceData


class VerifiedCitationInfo(BaseModel):
    title: str
    authors: List[str] = Field(default_factory=list)
    year: Optional[int] = None
    venue: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None


class CandidateResult(BaseModel):
    source_api: str = Field(..., description="The API that provided this candidate (e.g., 'Crossref', 'CiNii')")
    status: CandidateStatus = Field(..., description="Search result classification for this API")
    confidence_score: Optional[float] = Field(0.0, ge=0.0, le=1.0, description="Similarity score calculated for this specific result (0.0 to 1.0)")
    verified_info: Optional[VerifiedCitationInfo] = Field(None, description="Verified metadata obtained from the API. None if not found.")
    bibtex: Optional[str] = Field(None, description="Formatted BibTeX string from this API")
    error: Optional[str] = Field(None, description="Non-sensitive API failure summary")


class EvidenceBundle(BaseModel):
    """Source-preserving evidence supplied to semantic reconstruction."""

    raw_text: str
    original: ReferenceData
    search_clues: ReferenceData
    extracted_dois: List[str] = Field(default_factory=list)
    trusted_doi: Optional[str] = None
    candidates: List[CandidateResult] = Field(default_factory=list)


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


class LLMReconstruction(BaseModel):
    """Structured response produced by the semantic reconstruction model."""

    bibtex: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_sources: List[str] = Field(default_factory=list)
    unresolved_fields: List[str] = Field(default_factory=list)
    summary: str = ""


class ReconstructionAttempt(BaseModel):
    attempt: int = Field(ge=1)
    path: ReconstructionPath
    candidate_bibtex: str
    validation: RustValidationResult
    source_url: Optional[str] = None
    quality_issues: List[str] = Field(default_factory=list)
    filled_fields: List[str] = Field(default_factory=list)
    llm_result: Optional[LLMReconstruction] = None


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
    validation: Optional[RustValidationResult] = None
    attempts: List[ReconstructionAttempt] = Field(default_factory=list)
    review_reason: Optional[str] = None


class ReconstructionReport(BaseModel):
    """Typed audit report for one metadata_extraction document."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1"] = "1"
    input_path: Path
    bibtex_output_path: Path
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

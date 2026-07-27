# models/output_models.py
from typing import List, Optional
from pydantic import BaseModel, Field
from .input_models import ReferenceData
from core.constants import CandidateStatus, ReconstructionOutcome, ReconstructionPath


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
    llm_result: Optional[LLMReconstruction] = None


class ProcessedReference(BaseModel):
    ref_id: str = Field(..., description="Stable fragment ID assigned during initialization")
    outcome: ReconstructionOutcome
    original_data: ReferenceData = Field(..., description="The source fragment before clue enrichment")
    candidates: List[CandidateResult] = Field(default_factory=list, description="List of all matching results from various APIs, sorted by score")
    evidence: Optional[EvidenceBundle] = None
    reconstruction_path: Optional[ReconstructionPath] = None
    reconstructed_bibtex: Optional[str] = None
    validation: Optional[RustValidationResult] = None
    attempts: List[ReconstructionAttempt] = Field(default_factory=list)
    review_reason: Optional[str] = None

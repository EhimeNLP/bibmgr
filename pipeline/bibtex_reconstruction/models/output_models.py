# models/output_models.py
from typing import List, Optional, Any
from pydantic import BaseModel, Field
from models.input_models import ReferenceData
from core.constants import ProcessingStatus

class VerifiedCitationInfo(BaseModel):
    title: str
    authors: List[str] = Field(default_factory=list)
    year: Optional[int] = None
    venue: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None

class CandidateResult(BaseModel):
    source_api: str = Field(..., description="The API that provided this candidate (e.g., 'Crossref', 'CiNii')")
    status: ProcessingStatus = Field(..., description="Status of this specific API's result: 'success', 'needs_review', 'api_error', or 'not_found'")
    confidence_score: Optional[float] = Field(0.0, ge=0.0, le=1.0, description="Similarity score calculated for this specific result (0.0 to 1.0)")
    verified_info: Optional[VerifiedCitationInfo] = Field(None, description="Verified metadata obtained from the API. None if not found.")
    bibtex: Optional[str] = Field(None, description="Formatted BibTeX string from this API")

class ProcessedReference(BaseModel):
    ref_id: str = Field(..., description="Corresponds exactly to references[].id in JSON schema")
    overall_status: str = Field(..., description="Overall system status: 'success', 'needs_review', or 'not_found'")
    original_data: ReferenceData = Field(..., description="The raw reference data extracted from a PDF.")
    candidates: List[CandidateResult] = Field(default_factory=list, description="List of all matching results from various APIs, sorted by score")

class OutputData(BaseModel):
    title: str = Field(..., description="Title of the root document")
    authors: List[str] = Field(default_factory=list, description="Authors of the root document")
    year: Optional[Any] = Field(None, description="Publication year of the root document")
    doi: Optional[str] = Field(None, description="DOI of the root document")
    abstract: str = Field(..., description="Abstract of the root document")
    reference_count: int = Field(..., description="Total number of references")
    processed_references: List[ProcessedReference] = Field(default_factory=list, description="List of references enriched with API data")
    saved_files: List[Any] = Field(default_factory=list, description="Files associated with the root document")
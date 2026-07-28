# models/__init__.py

"""
Data Models Package.
Exposes both input and output Pydantic models for easy access.
"""

from .input_models import (
    DocumentMetadata,
    InputData,
    ReconstructionDocumentInput,
    ReferenceData,
)
from .output_models import (
    CandidateResult,
    EvidenceBundle,
    LLMReconstruction,
    ProcessedReference,
    ReconstructionReport,
    ReconstructionAttempt,
    RustValidationResult,
    ValidationDiagnostic,
    VerifiedCitationInfo,
)

__all__ = [
    "ReferenceData",
    "DocumentMetadata",
    "ReconstructionDocumentInput",
    "InputData",
    "VerifiedCitationInfo",
    "CandidateResult",
    "EvidenceBundle",
    "LLMReconstruction",
    "ReconstructionAttempt",
    "RustValidationResult",
    "ValidationDiagnostic",
    "ProcessedReference",
    "ReconstructionReport",
]

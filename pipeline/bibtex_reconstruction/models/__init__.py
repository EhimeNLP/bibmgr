# models/__init__.py

"""
Data Models Package.
Exposes both input and output Pydantic models for easy access.
"""

from .input_models import ReferenceData, InputData
from .output_models import (
    CandidateResult,
    EvidenceBundle,
    LLMReconstruction,
    ProcessedReference,
    ReconstructionAttempt,
    RustValidationResult,
    ValidationDiagnostic,
    VerifiedCitationInfo,
)

__all__ = [
    "ReferenceData",
    "InputData",
    "VerifiedCitationInfo",
    "CandidateResult",
    "EvidenceBundle",
    "LLMReconstruction",
    "ReconstructionAttempt",
    "RustValidationResult",
    "ValidationDiagnostic",
    "ProcessedReference",
]

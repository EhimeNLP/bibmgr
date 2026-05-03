# models/__init__.py

"""
Data Models Package.
Exposes both input and output Pydantic models for easy access.
"""

from .input_models import ReferenceData, DocumentRoot, InputData
from .output_models import VerifiedCitationInfo, CandidateResult, ProcessedReference, OutputData

__all__ = [
    "ReferenceData",
    "DocumentRoot",
    "InputData",
    "VerifiedCitationInfo",
    "CandidateResult",
    "ProcessedReference",
    "OutputData",
]
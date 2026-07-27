# models/input_models.py
from typing import List, Optional
from pydantic import BaseModel, Field


class ReferenceData(BaseModel):
    id: str
    title: Optional[str] = None
    authors: List[str] = Field(default_factory=list)
    year: Optional[str] = None
    doi: Optional[str] = None
    venue: Optional[str] = None
    raw_text: str
    context: Optional[str] = None


class InputData(BaseModel):
    """
    An architectural wrapper used internally by ReconstructionOrchestrator.
    It encapsulates a single reference and can be expanded in the future 
    to include system-level search parameters (e.g., timeout, retry counts).
    """
    parsed_data: ReferenceData

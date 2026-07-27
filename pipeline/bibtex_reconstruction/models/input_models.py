# models/input_models.py
from typing import List, Optional, Any, Union
from pydantic import BaseModel, Field

class ReferenceData(BaseModel):
    id: str
    title: Optional[str] = None
    authors: List[str] = Field(default_factory=list)
    year: Optional[str] = None
    doi: Optional[str] = None
    venue: Optional[str] = None
    raw_text: str
    citation_contexts: List[Any] = Field(default_factory=list)

class DocumentRoot(BaseModel):
    title: str
    authors: List[str] = Field(default_factory=list)
    year: Optional[Any] = None
    doi: Optional[str] = None
    abstract: str
    reference_count: Union[int, float]
    references: List[ReferenceData] = Field(default_factory=list)
    saved_files: List[Any] = Field(default_factory=list)

class InputData(BaseModel):
    """
    An architectural wrapper (envelope) used internally by the SearchOrchestrator.
    It encapsulates a single reference and can be expanded in the future 
    to include system-level search parameters (e.g., timeout, retry counts).
    """
    parsed_data: ReferenceData

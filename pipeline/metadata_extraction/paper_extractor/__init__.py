"""PDF paper metadata and reference-list extraction."""

from .extractors import (
    DEFAULT_EXTRACTION_JOBS,
    ExtractionConfig,
    ExtractionError,
    extract_paper,
    extract_papers,
)
from .models import ExtractionResult, PaperMetadata, Reference
from .summary import extract_essential_info, summarize_extraction

__all__ = [
    "DEFAULT_EXTRACTION_JOBS",
    "ExtractionConfig",
    "ExtractionError",
    "ExtractionResult",
    "PaperMetadata",
    "Reference",
    "extract_essential_info",
    "extract_paper",
    "extract_papers",
    "summarize_extraction",
]

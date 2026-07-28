"""Stable reconstruction state values."""

from enum import Enum


class CandidateStatus(str, Enum):
    MATCH = "match"
    WEAK_MATCH = "weak_match"
    API_ERROR = "api_error"
    NOT_FOUND = "not_found"


class ReconstructionOutcome(str, Enum):
    READY = "ready"
    MANUAL_REVIEW = "manual_review"


class ReconstructionPath(str, Enum):
    """The path that produced the final reconstruction candidate."""

    DOI_CONTENT_NEGOTIATION = "doi_content_negotiation"
    OFFICIAL_CITATION = "official_citation"
    METADATA_ENRICHMENT = "metadata_enrichment"
    LLM = "llm"

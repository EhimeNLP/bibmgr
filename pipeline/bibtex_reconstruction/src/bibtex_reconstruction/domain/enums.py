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

    LOCAL_DB = "local_db"
    DOI_CONTENT_NEGOTIATION = "doi_content_negotiation"
    OFFICIAL_CITATION = "official_citation"
    EXTERNAL_API = "external_api"
    METADATA_ENRICHMENT = "metadata_enrichment"
    METADATA_SYNTHESIS = "metadata_synthesis"


class BibtexSourceKind(str, Enum):
    """The provenance of an exact BibTeX representation."""

    LOCAL_DB = "local_db"
    API_EXPORT = "api_export"
    OFFICIAL_CITATION = "official_citation"
    DOI_CONTENT_NEGOTIATION = "doi_content_negotiation"
    METADATA_SYNTHESIS = "metadata_synthesis"
    FINAL = "final"


class LLMTask(str, Enum):
    """The two LLM tasks authorized by the initialization pipeline."""

    QUERY_IMPROVEMENT = "query_improvement"
    KEY_CONCEPT_GENERATION = "key_concept_generation"

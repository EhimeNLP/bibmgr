"""External bibliography metadata clients."""

from .arxiv import ArxivClient
from .crossref import CrossrefClient
from .cinii import CiNiiClient
from .semantic_scholar import SemanticScholarClient
from .jstage import JStageClient
from .doi import DoiContentNegotiationClient
from .citation_site import OfficialCitation, OfficialCitationClient

__all__ = [
    "CrossrefClient",
    "CiNiiClient",
    "SemanticScholarClient",
    "JStageClient",
    "ArxivClient",
    "DoiContentNegotiationClient",
    "OfficialCitation",
    "OfficialCitationClient",
]

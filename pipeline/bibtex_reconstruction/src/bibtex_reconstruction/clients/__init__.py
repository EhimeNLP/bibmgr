"""External bibliography metadata clients."""

from .arxiv import ArxivClient
from .acl_anthology import AclAnthologyClient
from .crossref import CrossrefClient
from .cinii import CiNiiClient
from .semantic_scholar import SemanticScholarClient
from .jstage import JStageClient
from .doi import DoiContentNegotiationClient
from .citation_site import OfficialCitation, OfficialCitationClient
from .local_db import LocalDBClient

__all__ = [
    "CrossrefClient",
    "AclAnthologyClient",
    "CiNiiClient",
    "SemanticScholarClient",
    "JStageClient",
    "ArxivClient",
    "DoiContentNegotiationClient",
    "OfficialCitation",
    "OfficialCitationClient",
    "LocalDBClient",
]

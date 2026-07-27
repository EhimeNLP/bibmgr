# api_clients/__init__.py

"""
API Clients Package.
Exposes all individual API client classes for cleaner imports.
"""

from .arxiv import ArxivClient
from .crossref import CrossrefClient
from .cinii import CiNiiClient
from .semantic_scholar import SemanticScholarClient
from .jstage import JStageClient
from .doi import DoiContentNegotiationClient

__all__ = [
    "CrossrefClient",
    "CiNiiClient",
    "SemanticScholarClient",
    "JStageClient",
    "ArxivClient",
    "DoiContentNegotiationClient",
]

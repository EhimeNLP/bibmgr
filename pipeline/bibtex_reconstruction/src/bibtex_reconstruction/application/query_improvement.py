"""LLM-assisted search-query improvement without bibliographic generation."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections.abc import Sequence
from typing import Protocol

from ..clients.llm import (
    LLMProvider,
    LLMProviderError,
    create_preferred_llm_providers,
)
from ..config import settings
from ..domain import (
    LLMInvocationAudit,
    QueryImprovementAudit,
    ReferenceData,
    SearchQueryResponse,
)
from ..domain.enums import LLMTask


logger = logging.getLogger(__name__)


class QueryImprover(Protocol):
    def improve(self, reference: ReferenceData) -> QueryImprovementAudit:
        """Return bibliographic search-query hypotheses only."""


class ConfiguredQueryImprover:
    """Try configured local vLLM first and retain a replayable call audit."""

    def __init__(
        self,
        providers: Sequence[LLMProvider] | None = None,
        *,
        max_queries: int | None = None,
    ) -> None:
        self.providers = list(
            providers
            if providers is not None
            else create_preferred_llm_providers()
        )
        self.max_queries = (
            max_queries or settings.query_improvement_max_queries
        )

    def improve(self, reference: ReferenceData) -> QueryImprovementAudit:
        prompt = self._prompt(reference, self.max_queries)
        for provider in self.providers:
            label = getattr(provider, "provider_label", "api_llm")
            try:
                response = provider.generate(prompt, SearchQueryResponse)
            except LLMProviderError as exc:
                logger.warning(
                    "query improver unavailable provider=%s reason=%s",
                    label,
                    exc,
                )
                continue
            queries = self._normalize(
                response.queries,
                original=reference.title or "",
                limit=self.max_queries,
            )
            return QueryImprovementAudit(
                queries=queries,
                invocation=LLMInvocationAudit(
                    task=LLMTask.QUERY_IMPROVEMENT,
                    provider=label,
                    model=getattr(provider, "model", None),
                    prompt_sha256=hashlib.sha256(
                        prompt.encode("utf-8")
                    ).hexdigest(),
                    response=response.model_dump(mode="json"),
                ),
            )
        return QueryImprovementAudit()

    @staticmethod
    def _prompt(reference: ReferenceData, max_queries: int) -> str:
        payload = {
            "ref_id": reference.id,
            "title": reference.title,
            "authors": reference.authors,
            "year": reference.year,
            "venue": reference.venue,
            "pages": reference.pages,
            "publication_info": reference.publication_info,
            "doi": reference.doi,
            "raw_citation": reference.raw_text,
        }
        return (
            "You are an expert in scholarly bibliography and publication "
            "retrieval. Identify the exact cited work and produce high-recall "
            "search queries for academic APIs. Use every clue in the input: "
            "raw citation, title, authors, publication year, venue, pages, and "
            "DOI. The extracted title may contain OCR errors, page numbers, or "
            "other citation noise. Use your learned knowledge of papers, author "
            "teams, publication periods, conference and journal names, official "
            "titles, acronyms, and identifiers to correct or expand the query. "
            "When the venue, publisher, author names, or citation context "
            "suggests that the work was published in a non-English language, "
            "include one concise query in the likely original language using "
            "native title keywords and author names. "
            f"Return at most {max_queries} concise, diverse queries: prefer a "
            "likely official title, distinctive title terms plus authors, and "
            "venue/year evidence. A known DOI may be placed in a query. These "
            "are retrieval hypotheses only: do not return BibTeX, explanatory "
            "text, or a claim that any metadata is verified. Return only the "
            "required JSON object.\n\nCITATION EVIDENCE:\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
        )

    @staticmethod
    def _normalize(
        values: Sequence[str],
        *,
        original: str,
        limit: int,
    ) -> list[str]:
        result: list[str] = []
        original_key = " ".join(original.split()).casefold()
        for value in values:
            query = " ".join(str(value).split()).strip()
            query = re.sub(r"[\x00-\x1f\x7f]", "", query)
            if (
                not query
                or len(query) > 300
                or query.casefold() == original_key
                or query.casefold() in {item.casefold() for item in result}
            ):
                continue
            result.append(query)
            if len(result) >= limit:
                break
        return result

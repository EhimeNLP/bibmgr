from difflib import SequenceMatcher
from typing import Optional, Tuple
from urllib.parse import urlparse

import requests

from api_clients.base_client import BaseAPIClient
from models import InputData, VerifiedCitationInfo
from core.config import settings


class LocalDBClient(BaseAPIClient):
    """
    Client for searching the internal laboratory database.

    This client is disabled by default (config.yml: api.localdb.enabled: false).
    When enabled, it is called before any external API and its result short-circuits the
    remaining search pipeline (confidence_score = 1.0).

    To activate, set `api.localdb.enabled: true`. The BibMgR read endpoint is
    public, so this lookup never needs a write credential.
    """

    @property
    def api_name(self) -> str:
        return "Lab Local DB"

    @property
    def api_prefix(self) -> str:
        return "localdb"

    def _execute_search(self, input_data: InputData) -> Tuple[Optional[VerifiedCitationInfo], Optional[str]]:
        title = (input_data.parsed_data.title or "").strip()
        if not title:
            return None, None
        endpoint = settings.localdb_base_url
        parsed = urlparse(endpoint)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("The local DB URL must use HTTP or HTTPS.")
        if parsed.scheme == "http" and parsed.hostname not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise ValueError(
                "Plain HTTP is only allowed for a loopback local DB URL."
            )

        response = requests.get(
            endpoint,
            params={
                "query": title,
                "author": (
                    input_data.parsed_data.authors[0]
                    if input_data.parsed_data.authors
                    else ""
                ),
                "year": input_data.parsed_data.year or "",
                "limit": 10,
                "offset": 0,
            },
            timeout=settings.localdb_timeout,
        )
        response.raise_for_status()
        payload = response.json()
        matches = payload.get("items", []) if isinstance(payload, dict) else []
        candidates = [item for item in matches if isinstance(item, dict)]
        if not candidates:
            return None, None
        best = max(
            candidates,
            key=lambda item: SequenceMatcher(
                None,
                title.casefold(),
                str(item.get("title", "")).casefold(),
            ).ratio(),
        )
        score = SequenceMatcher(
            None,
            title.casefold(),
            str(best.get("title", "")).casefold(),
        ).ratio()
        if score < settings.similarity_threshold:
            return None, None
        metadata = VerifiedCitationInfo(
            title=str(best.get("title", "")),
            authors=[
                str(author)
                for author in best.get("authors", [])
                if isinstance(author, str)
            ],
            year=best.get("year") if isinstance(best.get("year"), int) else None,
            venue=best.get("venue") if isinstance(best.get("venue"), str) else None,
            doi=best.get("doi") if isinstance(best.get("doi"), str) else None,
            url=best.get("url") if isinstance(best.get("url"), str) else None,
        )
        bibtex = best.get("bibtex")
        return metadata, bibtex if isinstance(bibtex, str) else None

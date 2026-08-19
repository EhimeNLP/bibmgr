"""Authoritative ACL Anthology search backed by its official BibTeX dump."""

from __future__ import annotations

import gzip
import logging
import re
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import bibtexparser

from ..config import PROJECT_DIR, settings
from ..domain import InputData, VerifiedCitationInfo
from ..matching import (
    calculate_author_similarity,
    calculate_similarity,
    normalize_comparison_text,
)
from .base import APIClientError, BaseAPIClient


logger = logging.getLogger(__name__)

_SEARCH_STOPWORDS = {
    "and",
    "for",
    "from",
    "into",
    "method",
    "of",
    "the",
    "using",
    "with",
}


@dataclass(frozen=True)
class _AnthologyRecord:
    title: str
    authors: tuple[str, ...]
    publication_types: tuple[str, ...]
    year: int | None
    venue: str | None
    doi: str | None
    canonical_url: str
    raw_payload: dict[str, str]


class AclAnthologyClient(BaseAPIClient):
    """Search official ACL metadata and return the per-paper BibTeX export."""

    def __init__(self, *, cache_path: Path | None = None) -> None:
        super().__init__()
        configured = cache_path or settings.acl_anthology_cache_path
        self.cache_path = (
            configured
            if configured.is_absolute()
            else PROJECT_DIR / configured
        )
        self._dataset_lock = threading.Lock()
        self._records: list[_AnthologyRecord] | None = None
        self._exact_titles: dict[str, list[int]] = {}
        self._token_index: dict[str, set[int]] = {}

    @property
    def api_name(self) -> str:
        return "ACL Anthology"

    @property
    def api_prefix(self) -> str:
        return "acl_anthology"

    @property
    def authoritative_bibtex(self) -> bool:
        return True

    def _execute_search(self, input_data: InputData):
        records = self._load_records()
        reference = input_data.parsed_data
        query = reference.title or ""
        query_key = normalize_comparison_text(query)
        if not query_key:
            return None, None

        indices = self._shortlist(query_key, len(records))
        if not indices:
            return None, None
        selected = max(
            (records[index] for index in indices),
            key=lambda record: (
                self._score(reference, record),
                record.canonical_url,
            ),
        )

        bibtex_url = selected.canonical_url.rstrip("/") + ".bib"
        response = self._make_request(
            url=bibtex_url,
            operation="citation_export",
            required=False,
        )
        bibtex = response.text if response is not None else None
        metadata = VerifiedCitationInfo(
            title=selected.title,
            authors=list(selected.authors),
            publication_types=list(selected.publication_types),
            year=selected.year,
            venue=selected.venue,
            doi=selected.doi,
            url=selected.canonical_url,
            raw_payload=selected.raw_payload,
        )
        return metadata, bibtex

    def _load_records(self) -> list[_AnthologyRecord]:
        with self._dataset_lock:
            if self._records is not None:
                return self._records

            source = self._load_cached_source()
            library = bibtexparser.parse_string(source)
            records: list[_AnthologyRecord] = []
            exact: dict[str, list[int]] = defaultdict(list)
            tokens: dict[str, set[int]] = defaultdict(set)
            for entry in library.entries:
                fields = {
                    key.casefold(): field.value.strip()
                    for key, field in entry.fields_dict.items()
                    if field.value and field.value.strip()
                }
                record = self._record(fields, entry.entry_type)
                if record is None:
                    continue
                index = len(records)
                records.append(record)
                title_key = normalize_comparison_text(record.title)
                exact[title_key].append(index)
                for token in self._search_tokens(title_key):
                    tokens[token].add(index)

            if not records:
                raise APIClientError(
                    api_name=self.api_name,
                    operation="metadata_index",
                    error_type="EmptyAnthologyIndex",
                )
            self._records = records
            self._exact_titles = dict(exact)
            self._token_index = dict(tokens)
            logger.info(
                "ACL Anthology index loaded records=%d cache=%s",
                len(records),
                self.cache_path,
            )
            return records

    def _load_cached_source(self) -> str:
        cached = self.cache_path.exists()
        fresh = cached and self._cache_is_fresh()
        if fresh:
            return self.cache_path.read_text(encoding="utf-8")

        try:
            response = self._make_request(
                url=settings.acl_anthology_bibtex_url,
                operation="metadata_download",
            )
            assert response is not None
            content = response.content
            if content.startswith(b"\x1f\x8b"):
                content = gzip.decompress(content)
            source = content.decode("utf-8")
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.cache_path.with_suffix(
                self.cache_path.suffix + ".tmp"
            )
            temporary.write_text(source, encoding="utf-8")
            temporary.replace(self.cache_path)
            return source
        except Exception as exc:
            if cached:
                logger.warning(
                    "ACL Anthology refresh failed; using stale cache "
                    "error_type=%s",
                    exc.__class__.__name__,
                )
                return self.cache_path.read_text(encoding="utf-8")
            if isinstance(exc, APIClientError):
                raise
            raise APIClientError(
                api_name=self.api_name,
                operation="metadata_download",
                error_type=exc.__class__.__name__,
            ) from exc

    def _cache_is_fresh(self) -> bool:
        maximum_age = settings.acl_anthology_cache_max_age_hours * 3600
        return time.time() - self.cache_path.stat().st_mtime <= maximum_age

    def _shortlist(self, query_key: str, record_count: int) -> list[int]:
        exact = self._exact_titles.get(query_key)
        if exact:
            return exact

        overlap: Counter[int] = Counter()
        for token in self._search_tokens(query_key):
            overlap.update(self._token_index.get(token, ()))
        if overlap:
            return [index for index, _ in overlap.most_common(200)]
        return list(range(record_count))

    @staticmethod
    def _score(reference, record: _AnthologyRecord) -> float:
        query_key = normalize_comparison_text(reference.title or "")
        title_key = normalize_comparison_text(record.title)
        title_score = calculate_similarity(
            reference.title or "",
            record.title,
        )
        if len(title_key) >= 12 and title_key in query_key:
            title_score = 1.0
        if reference.authors and record.authors:
            return 0.70 * title_score + 0.30 * calculate_author_similarity(
                reference.authors,
                record.authors,
            )
        return title_score

    @staticmethod
    def _search_tokens(value: str) -> set[str]:
        return {
            token
            for token in value.split()
            if len(token) >= 3 and token not in _SEARCH_STOPWORDS
        }

    @staticmethod
    def _record(
        fields: dict[str, str],
        entry_type: str,
    ) -> _AnthologyRecord | None:
        title = fields.get("title", "")
        canonical_url = fields.get("url", "")
        parsed_url = urlparse(canonical_url)
        if (
            not title
            or parsed_url.hostname
            not in {"aclanthology.org", "www.aclanthology.org"}
        ):
            return None
        canonical_url = "https://aclanthology.org/" + parsed_url.path.strip("/") + "/"
        year_text = fields.get("year", "")
        year = int(year_text) if year_text.isdigit() else None
        authors = tuple(
            part.strip()
            for part in re.split(
                r"\s+and\s+",
                fields.get("author", "").strip(),
            )
            if part.strip()
        )
        return _AnthologyRecord(
            title=title,
            authors=authors,
            publication_types=(entry_type,),
            year=year,
            venue=fields.get("booktitle") or fields.get("journal"),
            doi=fields.get("doi"),
            canonical_url=canonical_url,
            raw_payload=fields,
        )

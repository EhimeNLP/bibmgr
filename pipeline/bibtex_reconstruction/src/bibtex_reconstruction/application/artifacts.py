"""Content-addressed artifacts for replayable reconstruction reports."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import PROJECT_DIR, settings
from ..domain import (
    ArtifactReference,
    ProcessedReference,
    ReconstructionRun,
)


class ArtifactStore:
    """Write immutable evidence and return stable manifest references."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._references: dict[str, ArtifactReference] = {}

    @property
    def references(self) -> list[ArtifactReference]:
        return sorted(
            self._references.values(),
            key=lambda item: item.artifact_id,
        )

    def add_bytes(
        self,
        data: bytes,
        *,
        media_type: str,
        suffix: str,
    ) -> str:
        digest = hashlib.sha256(data).hexdigest()
        artifact_id = f"sha256:{digest}"
        if artifact_id not in self._references:
            relative_path = f"{digest}{suffix}"
            self.root.mkdir(parents=True, exist_ok=True)
            destination = self.root / relative_path
            if not destination.exists():
                destination.write_bytes(data)
            self._references[artifact_id] = ArtifactReference(
                artifact_id=artifact_id,
                relative_path=relative_path,
                media_type=media_type,
                sha256=digest,
                byte_length=len(data),
            )
        return artifact_id

    def add_text(
        self,
        value: str,
        *,
        media_type: str,
        suffix: str,
    ) -> str:
        return self.add_bytes(
            value.encode("utf-8"),
            media_type=media_type,
            suffix=suffix,
        )

    def add_json(self, value: Any) -> str:
        payload = (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
            )
            + "\n"
        )
        return self.add_text(
            payload,
            media_type="application/json",
            suffix=".json",
        )

    def capture_reference(self, result: ProcessedReference) -> None:
        """Store raw evidence and attach artifact IDs to the report models."""

        for candidate in result.candidates:
            if (
                candidate.verified_info is not None
                and candidate.verified_info.raw_payload is not None
            ):
                candidate.metadata_artifact_id = self.add_json(
                    candidate.verified_info.raw_payload
                )
                candidate.verified_info.raw_payload = None
            if candidate.bibtex:
                candidate.bibtex_artifact_id = self.add_text(
                    candidate.bibtex,
                    media_type="application/x-bibtex",
                    suffix=".bib",
                )
        for group in result.doi_groups:
            for evidence in (
                group.official_citation,
                group.content_negotiation,
            ):
                if evidence is not None:
                    evidence.artifact_id = self.add_text(
                        evidence.bibtex,
                        media_type="application/x-bibtex",
                        suffix=".bib",
                    )
        if result.reconstructed_bibtex:
            result.final_artifact_id = self.add_text(
                result.reconstructed_bibtex,
                media_type="application/x-bibtex",
                suffix=".bib",
            )


def reconstruction_run() -> ReconstructionRun:
    """Return a secret-free snapshot of code and behavior configuration."""

    revision: str | None = None
    dirty: bool | None = None
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_DIR,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=PROJECT_DIR,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
        )
    except (OSError, subprocess.CalledProcessError):
        pass
    return ReconstructionRun(
        created_at=datetime.now(timezone.utc),
        code_revision=revision or None,
        working_tree_dirty=dirty,
        configuration={
            "similarity_threshold": settings.similarity_threshold,
            "trusted_doi_threshold": settings.trusted_doi_threshold,
            "direct_bibtex_threshold": settings.direct_bibtex_threshold,
            "source_priority": [
                "local_db",
                "official_citation",
                "doi_content_negotiation",
                "acl_anthology",
                "crossref",
                "semantic_scholar",
                "cinii",
                "jstage",
                "arxiv",
            ],
            "selection_fallbacks": [
                "provider_bibtex",
                "typed_metadata_synthesis",
                "arxiv_official_bibtex_with_year_variance",
            ],
            "query_improvement_enabled": (
                settings.query_improvement_enabled
            ),
            "query_improvement_max_queries": (
                settings.query_improvement_max_queries
            ),
            "query_improvement_max_rounds": (
                settings.query_improvement_max_rounds
            ),
            "local_llm_enabled": settings.local_llm_enabled,
            "local_llm_model": settings.local_llm_model,
        },
    )

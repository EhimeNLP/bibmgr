from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class PaperMetadata:
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    year: str | None = None
    doi: str | None = None
    abstract: str | None = None
    source: str | None = None
    confidence: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "doi": self.doi,
            "abstract": self.abstract,
            "source": self.source,
            "confidence": self.confidence,
            "raw": self.raw,
        }


@dataclass(slots=True)
class Reference:
    id: str
    raw_text: str
    title: str | None = None
    authors: list[str] = field(default_factory=list)
    year: str | None = None
    doi: str | None = None
    venue: str | None = None
    source: str | None = None
    confidence: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "raw_text": self.raw_text,
            "title": self.title,
            "authors": self.authors,
            "year": self.year,
            "doi": self.doi,
            "venue": self.venue,
            "source": self.source,
            "confidence": self.confidence,
            "raw": self.raw,
        }


@dataclass(slots=True)
class ExtractionResult:
    input_pdf: Path
    metadata: PaperMetadata
    references: list[Reference]
    warnings: list[str] = field(default_factory=list)
    saved_files: list[Path] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "input_pdf": str(self.input_pdf),
            "engine": "paddleocr-vl",
            "metadata": self.metadata.to_dict(),
            "references": [reference.to_dict() for reference in self.references],
            "warnings": self.warnings,
            "saved_files": [str(path) for path in self.saved_files],
        }

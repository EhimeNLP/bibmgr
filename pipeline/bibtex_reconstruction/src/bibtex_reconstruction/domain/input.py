"""Input contracts for metadata_extraction and reconstruction tasks."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _normalize_extracted_year(value: object) -> object:
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return value


class ReferenceData(BaseModel):
    """One reference extracted from the source document."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: str | None = None
    doi: str | None = None
    venue: str | None = Field(
        default=None,
        description=(
            "Unnormalized publication hint extracted from the citation; "
            "it may include volume, issue, or page text."
        ),
    )
    pages: str | None = None
    publication_info: str | None = None
    raw_text: str = Field(min_length=1)
    context: str | None = None
    citation_contexts: list[str] = Field(default_factory=list)

    @field_validator("year", mode="before")
    @classmethod
    def normalize_year_type(cls, value: object) -> object:
        return _normalize_extracted_year(value)

    @property
    def comparison_year(self) -> int | None:
        """Return a four-digit year for matching while preserving raw suffixes."""

        if not self.year:
            return None
        match = re.search(r"(?<!\d)(\d{4})(?!\d)", self.year)
        return int(match.group(1)) if match else None


class DocumentMetadata(BaseModel):
    """Metadata for the document whose references are reconstructed."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: str | None = None
    doi: str | None = None
    abstract: str | None = None

    @field_validator("year", mode="before")
    @classmethod
    def normalize_year_type(cls, value: object) -> object:
        return _normalize_extracted_year(value)


class ReconstructionDocumentInput(DocumentMetadata):
    """The JSON document emitted by metadata_extraction."""

    reference_count: int = Field(ge=0)
    references: list[ReferenceData]

    @model_validator(mode="after")
    def validate_references(self) -> ReconstructionDocumentInput:
        if self.reference_count != len(self.references):
            raise ValueError(
                "reference_count must equal the number of references"
            )
        ids = [reference.id for reference in self.references]
        if len(ids) != len(set(ids)):
            raise ValueError("references[].id values must be unique")
        return self

    def document_metadata(self) -> DocumentMetadata:
        """Return root metadata without the reference collection."""

        return DocumentMetadata.model_validate(
            self.model_dump(exclude={"reference_count", "references"})
        )


class InputData(BaseModel):
    """Internal envelope for processing one extracted reference."""

    parsed_data: ReferenceData

"""Transport request and persisted-reference response models."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictRequest(BaseModel):
    """Reject misspelled transport fields instead of silently ignoring them."""

    model_config = ConfigDict(extra="forbid")


class AnalyzeRequest(StrictRequest):
    source: str
    profile: str = "laboratory"
    mode: Literal["strict", "tolerant"] = "tolerant"


class ApplyFixesRequest(StrictRequest):
    source: str
    source_revision: str = Field(min_length=1)
    fix_ids: list[str] = Field(min_length=1)
    profile: str = "laboratory"


class RegistrationRequest(StrictRequest):
    source: str
    policy: str = "laboratory"


class ExportRequest(StrictRequest):
    source: str
    profile: str = "laboratory"


class CitationContextInput(StrictRequest):
    source_paper_title: str | None = Field(default=None, max_length=2048)
    source_file_name: str | None = Field(default=None, max_length=1024)
    before: str | None = Field(default=None, max_length=20_000)
    context: str = Field(min_length=1, max_length=20_000)
    after: str | None = Field(default=None, max_length=20_000)


class RegisterReferencesRequest(StrictRequest):
    bibtex: str = Field(min_length=1)
    source: Literal["manual", "file"]
    citation_contexts: list[CitationContextInput] = Field(
        default_factory=list, max_length=1000
    )


class UpdateReferenceRequest(StrictRequest):
    bibtex: str = Field(min_length=1)
    source_revision: str = Field(
        pattern=r"^sha256:[0-9a-f]{64}$"
    )


class RestoreReferenceRevisionRequest(StrictRequest):
    target_revision: int = Field(ge=1)
    expected_head_revision: int = Field(ge=1)


class AddCitationContextsRequest(StrictRequest):
    contexts: list[CitationContextInput] = Field(min_length=1, max_length=1000)


class EmailLoginStartRequest(StrictRequest):
    email: str = Field(min_length=3, max_length=320)


class EmailLoginVerifyRequest(StrictRequest):
    email: str = Field(min_length=3, max_length=320)
    code: str = Field(pattern=r"^[0-9]{8}$")


class EmailLoginStartResponse(BaseModel):
    schema_version: Literal["1"] = "1"
    accepted: Literal[True] = True
    message: str


class AuthenticatedUserResponse(BaseModel):
    id: str
    email: str


class AuthenticationSessionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_version: Literal["1"] = "1"
    authenticated: bool
    user: AuthenticatedUserResponse | None = None
    csrf_token: str | None = Field(
        default=None, serialization_alias="csrfToken"
    )


class ReferenceRevisionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    revision: int
    action: Literal[
        "baseline", "create", "update", "delete", "restore", "context"
    ]
    actor: AuthenticatedUserResponse
    occurred_at: datetime = Field(serialization_alias="occurredAt")
    restored_from_revision: int | None = Field(
        default=None, serialization_alias="restoredFromRevision"
    )
    title: str | None = None
    source_revision: str | None = Field(
        default=None, serialization_alias="sourceRevision"
    )
    submitted_bibtex: str | None = Field(
        default=None, serialization_alias="submittedBibtex"
    )
    canonical_bibtex: str | None = Field(
        default=None, serialization_alias="canonicalBibtex"
    )
    restorable: bool


class ReferenceHistoryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    reference_id: str = Field(serialization_alias="referenceId")
    head_revision: int = Field(serialization_alias="headRevision")
    exists: bool
    revisions: list[ReferenceRevisionResponse]


class ReferenceHistorySummaryResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    reference_id: str = Field(serialization_alias="referenceId")
    head_revision: int = Field(serialization_alias="headRevision")
    exists: bool
    title: str | None = None
    latest_action: Literal[
        "baseline", "create", "update", "delete", "restore", "context"
    ] = Field(serialization_alias="latestAction")
    updated_at: datetime = Field(serialization_alias="updatedAt")


class ReferenceHistoryPageResponse(BaseModel):
    items: list[ReferenceHistorySummaryResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)


class CitationContextResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    source_paper_title: str | None = Field(
        default=None, serialization_alias="sourcePaperTitle"
    )
    source_file_name: str | None = Field(
        default=None, serialization_alias="sourceFileName"
    )
    before: str | None = None
    context: str
    after: str | None = None


class ReferenceResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str
    authors: list[str]
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    url: str | None = None
    bibtex_key: str | None = Field(
        default=None, serialization_alias="bibtexKey"
    )
    bibtex: str
    source_revision: str = Field(serialization_alias="sourceRevision")
    citation_contexts: list[CitationContextResponse] = Field(
        default_factory=list, serialization_alias="citationContexts"
    )
    created_at: datetime = Field(serialization_alias="createdAt")
    updated_at: datetime = Field(serialization_alias="updatedAt")


class RegisterReferencesResponse(BaseModel):
    reference: ReferenceResponse
    references: list[ReferenceResponse]


class ReferencePageResponse(BaseModel):
    items: list[ReferenceResponse]
    total: int = Field(ge=0)
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)

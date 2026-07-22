"""Transport request models; bibliography DTOs remain owned by Rust."""

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

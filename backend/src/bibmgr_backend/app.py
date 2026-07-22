"""FastAPI transport over the shared native engine."""

from typing import Annotated, Any, Literal, Protocol

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .models import (
    AnalyzeRequest,
    ApplyFixesRequest,
    ExportRequest,
    RegistrationRequest,
)
from .native import NativeCallError, NativeEngine


class ErrorPayload(BaseModel):
    """Application-owned error details advertised by OpenAPI."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1)
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Schema-v1 error envelope advertised by OpenAPI."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1"]
    error: ErrorPayload


REQUEST_VALIDATION_RESPONSES: dict[int, dict[str, Any]] = {
    422: {
        "description": "Invalid request",
        "model": ErrorResponse,
    }
}


class Engine(Protocol):
    def analyze(self, source: str, profile: str, mode: str) -> dict[str, Any]: ...

    def apply_fixes(
        self, source: str, source_revision: str, fix_ids: list[str], profile: str
    ) -> dict[str, Any]: ...

    def validate_for_registration(
        self, source: str, policy: str
    ) -> dict[str, Any]: ...

    def export_profiles(self) -> dict[str, Any]: ...

    def export_source(self, source: str, profile: str) -> dict[str, Any]: ...


def create_app(engine: Engine | None = None) -> FastAPI:
    application = FastAPI(
        title="bibmgr backend adapter",
        version="1.0.0",
        description="HTTP transport for the shared Rust BibTeX core",
    )
    selected_engine: Engine = engine or NativeEngine()

    def get_engine() -> Engine:
        return selected_engine

    EngineDependency = Annotated[Engine, Depends(get_engine)]

    def error_response(status_code: int, code: str, message: str) -> JSONResponse:
        return JSONResponse(
            status_code=status_code,
            content={
                "schema_version": "1",
                "error": {"code": code, "message": message},
            },
        )

    @application.exception_handler(NativeCallError)
    async def native_error_handler(
        _request: Request, error: NativeCallError
    ) -> JSONResponse:
        return error_response(error.status_code, error.code, str(error))

    @application.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        _request: Request, _error: RequestValidationError
    ) -> JSONResponse:
        return error_response(
            422,
            "invalid_request",
            "Request validation failed.",
        )

    @application.get("/healthz")
    def health() -> dict[str, str]:
        # Import is intentionally lazy; liveness must not invoke bibliography logic.
        return {"status": "ok"}

    @application.post(
        "/bibtex/analyze", responses=REQUEST_VALIDATION_RESPONSES
    )
    def analyze(
        request: AnalyzeRequest, native: EngineDependency
    ) -> dict[str, Any]:
        return native.analyze(request.source, request.profile, request.mode)

    @application.post(
        "/bibtex/fixes/apply", responses=REQUEST_VALIDATION_RESPONSES
    )
    def apply_fixes(
        request: ApplyFixesRequest, native: EngineDependency
    ) -> dict[str, Any]:
        return native.apply_fixes(
            request.source,
            request.source_revision,
            request.fix_ids,
            request.profile,
        )

    @application.post(
        "/bibtex/registration/validate", responses=REQUEST_VALIDATION_RESPONSES
    )
    def validate_registration(
        request: RegistrationRequest, native: EngineDependency
    ) -> dict[str, Any]:
        return native.validate_for_registration(request.source, request.policy)

    @application.get("/bibtex/export/profiles")
    def export_profiles(native: EngineDependency) -> dict[str, Any]:
        return native.export_profiles()

    @application.post(
        "/bibtex/export", responses=REQUEST_VALIDATION_RESPONSES
    )
    def export_source(
        request: ExportRequest, native: EngineDependency
    ) -> dict[str, Any]:
        return native.export_source(request.source, request.profile)

    return application


app = create_app()

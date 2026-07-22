"""FastAPI transport over the shared native engine."""

from typing import Annotated, Any, Protocol

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from .models import (
    AnalyzeRequest,
    ApplyFixesRequest,
    ExportRequest,
    RegistrationRequest,
)
from .native import NativeCallError, NativeEngine


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

    @application.exception_handler(NativeCallError)
    async def native_error_handler(
        _request: Request, error: NativeCallError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={
                "schema_version": "1",
                "error": {"code": error.code, "message": str(error)},
            },
        )

    @application.get("/healthz")
    def health() -> dict[str, str]:
        # Import is intentionally lazy; liveness must not invoke bibliography logic.
        return {"status": "ok"}

    @application.post("/bibtex/analyze")
    def analyze(
        request: AnalyzeRequest, native: EngineDependency
    ) -> dict[str, Any]:
        return native.analyze(request.source, request.profile, request.mode)

    @application.post("/bibtex/fixes/apply")
    def apply_fixes(
        request: ApplyFixesRequest, native: EngineDependency
    ) -> dict[str, Any]:
        return native.apply_fixes(
            request.source,
            request.source_revision,
            request.fix_ids,
            request.profile,
        )

    @application.post("/bibtex/registration/validate")
    def validate_registration(
        request: RegistrationRequest, native: EngineDependency
    ) -> dict[str, Any]:
        return native.validate_for_registration(request.source, request.policy)

    @application.get("/bibtex/export/profiles")
    def export_profiles(native: EngineDependency) -> dict[str, Any]:
        return native.export_profiles()

    @application.post("/bibtex/export")
    def export_source(
        request: ExportRequest, native: EngineDependency
    ) -> dict[str, Any]:
        return native.export_source(request.source, request.profile)

    return application


app = create_app()

"""FastAPI transport over the shared native engine and reference library."""

from collections import Counter
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
import json
import logging
import os
from threading import Lock
import time
from typing import Annotated, Any, Literal, Protocol
import uuid

from fastapi import Depends, FastAPI, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .auth import (
    SESSION_LIFETIME,
    AuthenticatedSession,
    AuthenticationManager,
    AuthenticationRateLimitError,
    AuthenticationRequiredError,
    CsrfValidationError,
    EmailDeliveryError,
)
from .database import SessionFactory
from .db_models import ReferenceAuditEvent
from .configuration import ApplicationConfiguration
from .library import (
    LibraryError,
    ReferenceLibrary,
    normalize_title_for_display,
    reference_response,
)
from .models import (
    AnalyzeRequest,
    AddCitationContextsRequest,
    ApplyFixesRequest,
    AuthenticatedUserResponse,
    AuthenticationSessionResponse,
    EmailLoginStartRequest,
    EmailLoginStartResponse,
    EmailLoginVerifyRequest,
    ExportRequest,
    ReferenceHistoryResponse,
    ReferenceHistoryPageResponse,
    ReferenceHistorySummaryResponse,
    ReferencePageResponse,
    ReferenceResponse,
    ReferenceRevisionResponse,
    RegisterReferencesRequest,
    RegisterReferencesResponse,
    RegistrationRequest,
    RestoreReferenceRevisionRequest,
    UpdateReferenceRequest,
    UpdateApplicationConfigurationRequest,
)
from .native import NativeCallError, NativeEngine


LOGGER = logging.getLogger("bibmgr.http")
if not LOGGER.handlers:
    _request_log_handler = logging.StreamHandler()
    _request_log_handler.setFormatter(logging.Formatter("%(message)s"))
    LOGGER.addHandler(_request_log_handler)
LOGGER.setLevel(logging.INFO)
LOGGER.propagate = False


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
AUTHENTICATED_WRITE_RESPONSES: dict[int, dict[str, Any]] = {
    401: {
        "description": "Authentication required",
        "model": ErrorResponse,
    },
    403: {
        "description": "CSRF validation failed",
        "model": ErrorResponse,
    },
}
AUTHENTICATION_REQUIRED_RESPONSES: dict[int, dict[str, Any]] = {
    401: {
        "description": "Authentication required",
        "model": ErrorResponse,
    }
}


class Engine(Protocol):
    def analyze(
        self,
        source: str,
        profile: str,
        mode: str,
        *,
        venue_registry: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def apply_fixes(
        self,
        source: str,
        source_revision: str,
        fix_ids: list[str],
        profile: str,
        *,
        venue_registry: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def validate_for_registration(
        self,
        source: str,
        policy: str,
        *,
        venue_registry: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def canonicalize_for_storage(
        self,
        source: str,
        policy: str,
        *,
        venue_registry: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def export_profiles(self) -> dict[str, Any]: ...

    def export_source(
        self,
        source: str,
        profile: str,
        *,
        venue_name_style: str = "full",
        profile_data: dict[str, Any] | None = None,
        venue_registry: dict[str, Any] | None = None,
    ) -> dict[str, Any]: ...

    def builtin_configuration(self) -> dict[str, Any]: ...

    def validate_export_profile(
        self, profile_data: dict[str, Any]
    ) -> dict[str, Any]: ...

    def validate_venue_registry(
        self, venue_registry: dict[str, Any]
    ) -> dict[str, Any]: ...


def create_app(
    engine: Engine | None = None,
    session_factory: Callable[[], Session] | None = None,
    registration_policy: str | None = None,
    authentication: AuthenticationManager | None = None,
) -> FastAPI:
    application = FastAPI(
        title="bibmgr backend",
        version="1.0.0",
        description=(
            "HTTP transport for the shared Rust BibTeX core and PostgreSQL "
            "reference library"
        ),
    )
    selected_engine: Engine = engine or NativeEngine()
    selected_session_factory = session_factory or SessionFactory
    library = ReferenceLibrary(selected_engine)
    configuration = ApplicationConfiguration(selected_engine)
    selected_authentication = authentication or AuthenticationManager()
    selected_registration_policy = (
        registration_policy
        if registration_policy is not None
        else os.environ.get("BIBMGR_REGISTRATION_POLICY", "archive")
    )
    request_counts: Counter[tuple[str, str, int]] = Counter()
    request_duration_seconds: Counter[tuple[str, str]] = Counter()
    request_duration_samples: Counter[tuple[str, str]] = Counter()
    metrics_lock = Lock()

    @application.middleware("http")
    async def observe_request(
        request: Request,
        call_next: Callable[[Request], Any],
    ) -> Response:
        request_id = _request_id(request.headers.get("X-Request-ID"))
        started_at = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            duration = time.perf_counter() - started_at
            route = request.scope.get("route")
            route_path = getattr(route, "path", "unmatched")
            key = (request.method, route_path)
            with metrics_lock:
                request_counts[(request.method, route_path, status_code)] += 1
                request_duration_seconds[key] += duration
                request_duration_samples[key] += 1
            LOGGER.info(
                json.dumps(
                    {
                        "event": "http_request",
                        "request_id": request_id,
                        "method": request.method,
                        "route": route_path,
                        "status_code": status_code,
                        "duration_ms": round(duration * 1000, 3),
                    },
                    separators=(",", ":"),
                )
            )

    def get_engine() -> Engine:
        return selected_engine

    EngineDependency = Annotated[Engine, Depends(get_engine)]

    def get_session() -> Iterator[Session]:
        with selected_session_factory() as session:
            yield session

    SessionDependency = Annotated[Session, Depends(get_session)]

    @contextmanager
    def write_transaction(session: Session) -> Iterator[None]:
        try:
            yield
            session.commit()
        except Exception:
            session.rollback()
            raise

    def require_write_session(
        request: Request,
        session: SessionDependency,
        csrf_token: Annotated[
            str | None, Header(alias="X-CSRF-Token")
        ] = None,
    ) -> AuthenticatedSession:
        return selected_authentication.require_write_session(
            session,
            token=request.cookies.get(
                selected_authentication.cookie_name
            ),
            csrf_token=csrf_token,
        )

    def require_authenticated_session(
        request: Request,
        session: SessionDependency,
    ) -> AuthenticatedSession:
        authenticated = selected_authentication.authenticate(
            session,
            request.cookies.get(selected_authentication.cookie_name),
        )
        if authenticated is None:
            raise AuthenticationRequiredError(
                "Login is required for this operation."
            )
        return authenticated

    AuthenticatedSessionDependency = Annotated[
        AuthenticatedSession, Depends(require_authenticated_session)
    ]
    WriteSessionDependency = Annotated[
        AuthenticatedSession, Depends(require_write_session)
    ]

    def error_response(
        status_code: int,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
    ) -> JSONResponse:
        error: dict[str, Any] = {"code": code, "message": message}
        if details:
            error["details"] = details
        return JSONResponse(
            status_code=status_code,
            content={
                "schema_version": "1",
                "error": error,
            },
        )

    @application.exception_handler(NativeCallError)
    async def native_error_handler(
        _request: Request, error: NativeCallError
    ) -> JSONResponse:
        return error_response(error.status_code, error.code, str(error))

    @application.exception_handler(LibraryError)
    async def library_error_handler(
        _request: Request, error: LibraryError
    ) -> JSONResponse:
        return error_response(
            error.status_code,
            error.code,
            str(error),
            details=error.details,
        )

    @application.exception_handler(SQLAlchemyError)
    async def database_error_handler(
        _request: Request, _error: SQLAlchemyError
    ) -> JSONResponse:
        return error_response(
            503,
            "database_unavailable",
            "The reference database is unavailable.",
        )

    @application.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        _request: Request, _error: RequestValidationError
    ) -> JSONResponse:
        return error_response(
            422,
            "invalid_request",
            "Request validation failed.",
        )

    @application.exception_handler(AuthenticationRequiredError)
    async def authentication_required_handler(
        _request: Request, error: AuthenticationRequiredError
    ) -> JSONResponse:
        return error_response(
            401,
            "authentication_required",
            str(error),
        )

    @application.exception_handler(CsrfValidationError)
    async def csrf_validation_handler(
        _request: Request, error: CsrfValidationError
    ) -> JSONResponse:
        return error_response(403, "csrf_validation_failed", str(error))

    @application.exception_handler(AuthenticationRateLimitError)
    async def authentication_rate_limit_handler(
        _request: Request, error: AuthenticationRateLimitError
    ) -> JSONResponse:
        response = error_response(
            429,
            "authentication_rate_limited",
            str(error),
        )
        response.headers["Retry-After"] = str(error.retry_after)
        return response

    @application.exception_handler(EmailDeliveryError)
    async def email_delivery_handler(
        _request: Request, error: EmailDeliveryError
    ) -> JSONResponse:
        return error_response(
            503,
            "email_delivery_failed",
            str(error),
        )

    def authentication_response(
        authenticated: AuthenticatedSession | None,
    ) -> AuthenticationSessionResponse:
        if authenticated is None:
            return AuthenticationSessionResponse(authenticated=False)
        return AuthenticationSessionResponse(
            authenticated=True,
            user=AuthenticatedUserResponse(
                id=str(authenticated.user.id),
                email=authenticated.user.email,
            ),
            csrf_token=selected_authentication.csrf_token(
                authenticated.token
            ),
        )

    def revision_response(
        event: ReferenceAuditEvent,
    ) -> ReferenceRevisionResponse:
        snapshot = event.after_data or event.before_data or {}
        title = snapshot.get("title") or snapshot.get("citation_key")
        source_revision = snapshot.get("source_revision")
        canonical_bibtex = snapshot.get("canonical_bibtex")
        if not isinstance(canonical_bibtex, str):
            canonical_bibtex = snapshot.get("raw_bibtex")
        submitted_bibtex = snapshot.get("submitted_bibtex")
        if not isinstance(submitted_bibtex, str):
            submitted_bibtex = canonical_bibtex
        return ReferenceRevisionResponse(
            revision=event.revision,
            action=event.action,
            actor=AuthenticatedUserResponse(
                id=str(event.actor.id),
                email=event.actor.email,
            ),
            occurred_at=event.occurred_at,
            restored_from_revision=event.restored_from_revision,
            title=normalize_title_for_display(title)
            if isinstance(title, str)
            else None,
            source_revision=(
                source_revision
                if isinstance(source_revision, str)
                else None
            ),
            submitted_bibtex=(
                submitted_bibtex
                if isinstance(submitted_bibtex, str)
                else None
            ),
            canonical_bibtex=(
                canonical_bibtex
                if isinstance(canonical_bibtex, str)
                else None
            ),
            restorable=(
                isinstance(event.after_data, dict)
                and event.after_data.get("snapshot_version") in (1, 2)
            ),
        )

    @application.get("/healthz")
    def health() -> dict[str, str]:
        # Import is intentionally lazy; liveness must not invoke bibliography logic.
        return {"status": "ok"}

    @application.get("/readyz")
    def readiness(session: SessionDependency) -> dict[str, str]:
        session.execute(text("SELECT 1"))
        return {"status": "ready"}

    @application.get("/metrics", response_class=PlainTextResponse)
    def metrics() -> str:
        lines = [
            "# HELP bibmgr_http_requests_total HTTP requests handled.",
            "# TYPE bibmgr_http_requests_total counter",
        ]
        with metrics_lock:
            for (method, route, status), count in sorted(
                request_counts.items()
            ):
                labels = _metric_labels(
                    method=method, route=route, status=str(status)
                )
                lines.append(
                    f"bibmgr_http_requests_total{{{labels}}} {count}"
                )
            lines.extend(
                [
                    (
                        "# HELP bibmgr_http_request_duration_seconds "
                        "HTTP request duration."
                    ),
                    "# TYPE bibmgr_http_request_duration_seconds summary",
                ]
            )
            for (method, route), duration in sorted(
                request_duration_seconds.items()
            ):
                labels = _metric_labels(method=method, route=route)
                lines.append(
                    "bibmgr_http_request_duration_seconds_sum"
                    f"{{{labels}}} {duration:.9f}"
                )
                lines.append(
                    "bibmgr_http_request_duration_seconds_count"
                    f"{{{labels}}} "
                    f"{request_duration_samples[(method, route)]}"
                )
        return "\n".join(lines) + "\n"

    @application.post(
        "/auth/email/start",
        status_code=202,
        response_model=EmailLoginStartResponse,
        responses={
            **REQUEST_VALIDATION_RESPONSES,
            429: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    def start_email_login(
        login: EmailLoginStartRequest,
        request: Request,
        session: SessionDependency,
    ) -> EmailLoginStartResponse:
        with write_transaction(session):
            delivery = selected_authentication.reserve_login_code(
                session,
                email=login.email,
                request_ip=(
                    request.client.host if request.client else None
                ),
            )
        if delivery is not None:
            try:
                selected_authentication.deliver_login_code(delivery)
            except EmailDeliveryError:
                with write_transaction(session):
                    selected_authentication.mark_login_delivery_failed(
                        session,
                        delivery.challenge_id,
                    )
                raise
        return EmailLoginStartResponse(
            message=(
                "If the address is eligible, a login code has been sent."
            )
        )

    @application.post(
        "/auth/email/verify",
        response_model=AuthenticationSessionResponse,
        responses={
            **REQUEST_VALIDATION_RESPONSES,
            401: {"model": ErrorResponse},
        },
    )
    def verify_email_login(
        login: EmailLoginVerifyRequest,
        session: SessionDependency,
    ) -> JSONResponse:
        with write_transaction(session):
            authenticated = selected_authentication.verify_login(
                session,
                email=login.email,
                code=login.code,
            )
        if authenticated is None:
            return error_response(
                401,
                "invalid_login_code",
                "The login code is invalid or has expired.",
            )

        payload = authentication_response(authenticated).model_dump(
            mode="json", by_alias=True
        )
        response = JSONResponse(content=payload)
        response.set_cookie(
            key=selected_authentication.cookie_name,
            value=authenticated.token,
            max_age=int(SESSION_LIFETIME.total_seconds()),
            path=selected_authentication.cookie_path,
            secure=selected_authentication.secure_cookie,
            httponly=True,
            samesite="lax",
        )
        return response

    @application.get(
        "/auth/session",
        response_model=AuthenticationSessionResponse,
    )
    def get_authentication_session(
        request: Request,
        session: SessionDependency,
    ) -> AuthenticationSessionResponse:
        authenticated = selected_authentication.authenticate(
            session,
            request.cookies.get(selected_authentication.cookie_name),
        )
        return authentication_response(authenticated)

    @application.post(
        "/auth/logout",
        status_code=204,
        responses={
            401: {"model": ErrorResponse},
            403: {"model": ErrorResponse},
        },
    )
    def logout(
        authenticated: WriteSessionDependency,
        session: SessionDependency,
    ) -> Response:
        with write_transaction(session):
            selected_authentication.revoke(authenticated)
        response = Response(status_code=204)
        response.delete_cookie(
            key=selected_authentication.cookie_name,
            path=selected_authentication.cookie_path,
            secure=selected_authentication.secure_cookie,
            httponly=True,
            samesite="lax",
        )
        return response

    @application.post(
        "/bibtex/analyze",
        responses={
            **REQUEST_VALIDATION_RESPONSES,
            **AUTHENTICATION_REQUIRED_RESPONSES,
        },
    )
    def analyze(
        request: AnalyzeRequest,
        native: EngineDependency,
        session: SessionDependency,
        _authenticated: AuthenticatedSessionDependency,
    ) -> dict[str, Any]:
        return native.analyze(
            request.source,
            request.profile,
            request.mode,
            venue_registry=configuration.venue_registry(session),
        )

    @application.post(
        "/bibtex/fixes/apply",
        responses={
            **REQUEST_VALIDATION_RESPONSES,
            **AUTHENTICATION_REQUIRED_RESPONSES,
        },
    )
    def apply_fixes(
        request: ApplyFixesRequest,
        native: EngineDependency,
        session: SessionDependency,
        _authenticated: AuthenticatedSessionDependency,
    ) -> dict[str, Any]:
        return native.apply_fixes(
            request.source,
            request.source_revision,
            request.fix_ids,
            request.profile,
            venue_registry=configuration.venue_registry(session),
        )

    @application.post(
        "/bibtex/registration/validate",
        responses={
            **REQUEST_VALIDATION_RESPONSES,
            **AUTHENTICATION_REQUIRED_RESPONSES,
        },
    )
    def validate_registration(
        request: RegistrationRequest,
        native: EngineDependency,
        session: SessionDependency,
        _authenticated: AuthenticatedSessionDependency,
    ) -> dict[str, Any]:
        return native.validate_for_registration(
            request.source,
            request.policy,
            venue_registry=configuration.venue_registry(session),
        )

    @application.post(
        "/bibtex/registration/canonicalize",
        responses={
            **REQUEST_VALIDATION_RESPONSES,
            **AUTHENTICATION_REQUIRED_RESPONSES,
        },
    )
    def canonicalize_registration_source(
        request: RegistrationRequest,
        native: EngineDependency,
        session: SessionDependency,
        _authenticated: AuthenticatedSessionDependency,
    ) -> dict[str, Any]:
        return native.canonicalize_for_storage(
            request.source,
            request.policy,
            venue_registry=configuration.venue_registry(session),
        )

    @application.get(
        "/bibtex/export/profiles",
        responses=AUTHENTICATION_REQUIRED_RESPONSES,
    )
    def export_profiles(
        session: SessionDependency,
        _authenticated: AuthenticatedSessionDependency,
    ) -> dict[str, Any]:
        return configuration.export_profile_catalog(session)

    @application.post(
        "/bibtex/export",
        responses={
            **REQUEST_VALIDATION_RESPONSES,
            **AUTHENTICATION_REQUIRED_RESPONSES,
        },
    )
    def export_source(
        request: ExportRequest,
        native: EngineDependency,
        session: SessionDependency,
        _authenticated: AuthenticatedSessionDependency,
    ) -> dict[str, Any]:
        return native.export_source(
            request.source,
            request.profile,
            venue_name_style=request.venue_name_style,
            profile_data=configuration.export_profile(
                session, request.profile
            ),
            venue_registry=configuration.venue_registry(session),
        )

    @application.get(
        "/settings/configuration",
        responses=AUTHENTICATION_REQUIRED_RESPONSES,
    )
    def get_application_configuration(
        session: SessionDependency,
        _authenticated: AuthenticatedSessionDependency,
    ) -> dict[str, Any]:
        return configuration.catalog(session)

    @application.get(
        "/settings/configuration-history",
        responses=AUTHENTICATION_REQUIRED_RESPONSES,
    )
    def get_application_configuration_history(
        kind: Literal["export_profile", "venue"],
        session: SessionDependency,
        _authenticated: AuthenticatedSessionDependency,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> dict[str, Any]:
        return configuration.history(
            session,
            kind=kind,
            limit=limit,
            offset=offset,
        )

    @application.put(
        "/settings/export-profiles/{profile_id}",
        responses={
            **REQUEST_VALIDATION_RESPONSES,
            **AUTHENTICATED_WRITE_RESPONSES,
            409: {"model": ErrorResponse},
        },
    )
    def update_export_profile(
        profile_id: str,
        request: UpdateApplicationConfigurationRequest,
        session: SessionDependency,
        authenticated: WriteSessionDependency,
    ) -> dict[str, Any]:
        with write_transaction(session):
            entry = configuration.save_export_profile(
                session,
                profile_id=profile_id,
                profile_data=request.data,
                expected_revision=request.expected_revision,
                actor_user_id=authenticated.user.id,
            )
        return {"schema_version": "1", "setting": entry}

    @application.put(
        "/settings/venues/{venue_id}",
        responses={
            **REQUEST_VALIDATION_RESPONSES,
            **AUTHENTICATED_WRITE_RESPONSES,
            409: {"model": ErrorResponse},
        },
    )
    def update_venue(
        venue_id: str,
        request: UpdateApplicationConfigurationRequest,
        session: SessionDependency,
        authenticated: WriteSessionDependency,
    ) -> dict[str, Any]:
        with write_transaction(session):
            entry = configuration.save_venue(
                session,
                venue_id=venue_id,
                venue_data=request.data,
                expected_revision=request.expected_revision,
                actor_user_id=authenticated.user.id,
            )
        return {"schema_version": "1", "setting": entry}

    @application.delete(
        "/settings/export-profiles/{profile_id}",
        responses={
            **REQUEST_VALIDATION_RESPONSES,
            **AUTHENTICATED_WRITE_RESPONSES,
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )
    def delete_export_profile(
        profile_id: str,
        expected_revision: Annotated[int, Query(ge=1)],
        session: SessionDependency,
        authenticated: WriteSessionDependency,
    ) -> dict[str, Any]:
        with write_transaction(session):
            result = configuration.delete_export_profile(
                session,
                profile_id=profile_id,
                expected_revision=expected_revision,
                actor_user_id=authenticated.user.id,
            )
        return {"schema_version": "1", **result}

    @application.delete(
        "/settings/venues/{venue_id}",
        responses={
            **REQUEST_VALIDATION_RESPONSES,
            **AUTHENTICATED_WRITE_RESPONSES,
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )
    def delete_venue(
        venue_id: str,
        expected_revision: Annotated[int, Query(ge=1)],
        session: SessionDependency,
        authenticated: WriteSessionDependency,
    ) -> dict[str, Any]:
        with write_transaction(session):
            result = configuration.delete_venue(
                session,
                venue_id=venue_id,
                expected_revision=expected_revision,
                actor_user_id=authenticated.user.id,
            )
        return {"schema_version": "1", **result}

    @application.get(
        "/reference-history",
        response_model=list[ReferenceHistorySummaryResponse],
        responses=AUTHENTICATION_REQUIRED_RESPONSES,
    )
    def list_reference_history(
        session: SessionDependency,
        _authenticated: AuthenticatedSessionDependency,
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[ReferenceHistorySummaryResponse]:
        summaries: list[ReferenceHistorySummaryResponse] = []
        for head, event, live_reference_id in library.list_history(
            session, limit=limit, offset=offset
        ):
            snapshot = event.after_data or event.before_data or {}
            title = snapshot.get("title") or snapshot.get(
                "citation_key"
            )
            summaries.append(
                ReferenceHistorySummaryResponse(
                    reference_id=str(head.reference_id),
                    head_revision=head.latest_revision,
                    exists=live_reference_id is not None,
                    title=normalize_title_for_display(title)
                    if isinstance(title, str)
                    else None,
                    latest_action=event.action,
                    updated_at=head.updated_at,
                )
            )
        return summaries

    @application.get(
        "/reference-history/page",
        response_model=ReferenceHistoryPageResponse,
        responses=AUTHENTICATION_REQUIRED_RESPONSES,
    )
    def page_reference_history(
        session: SessionDependency,
        _authenticated: AuthenticatedSessionDependency,
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> ReferenceHistoryPageResponse:
        summaries = list_reference_history(
            session=session,
            _authenticated=_authenticated,
            limit=limit,
            offset=offset,
        )
        return ReferenceHistoryPageResponse(
            items=summaries,
            total=library.count_history(session),
            limit=limit,
            offset=offset,
        )

    @application.get(
        "/references/{reference_id}/history",
        response_model=ReferenceHistoryResponse,
        responses={
            **AUTHENTICATION_REQUIRED_RESPONSES,
            404: {"model": ErrorResponse},
        },
    )
    def get_reference_history(
        reference_id: uuid.UUID,
        session: SessionDependency,
        _authenticated: AuthenticatedSessionDependency,
    ) -> ReferenceHistoryResponse:
        head, events, exists = library.get_history(
            session, reference_id
        )
        return ReferenceHistoryResponse(
            reference_id=str(reference_id),
            head_revision=head.latest_revision,
            exists=exists,
            revisions=[
                revision_response(event) for event in events
            ],
        )

    @application.post(
        "/references/{reference_id}/revert",
        response_model=ReferenceResponse,
        responses={
            **REQUEST_VALIDATION_RESPONSES,
            **AUTHENTICATED_WRITE_RESPONSES,
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )
    def revert_reference(
        reference_id: uuid.UUID,
        request: RestoreReferenceRevisionRequest,
        session: SessionDependency,
        authenticated: WriteSessionDependency,
    ) -> ReferenceResponse:
        with write_transaction(session):
            record = library.restore(
                session,
                reference_id=reference_id,
                target_revision=request.target_revision,
                expected_head_revision=request.expected_head_revision,
                actor_user_id=authenticated.user.id,
            )
        return reference_response(record)

    @application.get(
        "/references",
        response_model=list[ReferenceResponse],
        responses={
            **REQUEST_VALIDATION_RESPONSES,
            **AUTHENTICATION_REQUIRED_RESPONSES,
        },
    )
    def search_references(
        session: SessionDependency,
        _authenticated: AuthenticatedSessionDependency,
        query: Annotated[str, Query(max_length=512)] = "",
        limit: Annotated[int, Query(ge=1, le=100)] = 50,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[ReferenceResponse]:
        records = library.search(
            session, query, limit=limit, offset=offset
        )
        return [reference_response(record) for record in records]

    @application.get(
        "/references/page",
        response_model=ReferencePageResponse,
        responses={
            **REQUEST_VALIDATION_RESPONSES,
            **AUTHENTICATION_REQUIRED_RESPONSES,
        },
    )
    def page_references(
        session: SessionDependency,
        _authenticated: AuthenticatedSessionDependency,
        query: Annotated[str, Query(max_length=512)] = "",
        year: Annotated[int | None, Query(ge=1, le=9999)] = None,
        author: Annotated[str | None, Query(max_length=320)] = None,
        venue: Annotated[str | None, Query(max_length=512)] = None,
        identifier: Annotated[str | None, Query(max_length=512)] = None,
        entry_type: Annotated[str | None, Query(max_length=64)] = None,
        created_by: Annotated[str | None, Query(max_length=320)] = None,
        updated_from: datetime | None = None,
        updated_to: datetime | None = None,
        sort: Literal[
            "updated_desc",
            "updated_asc",
            "year_desc",
            "year_asc",
            "title_asc",
        ] = "updated_desc",
        limit: Annotated[int, Query(ge=1, le=100)] = 25,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> ReferencePageResponse:
        records, total = library.search_page(
            session,
            query,
            year=year,
            author=author,
            venue=venue,
            identifier=identifier,
            entry_type=entry_type,
            created_by=created_by,
            updated_from=updated_from,
            updated_to=updated_to,
            sort=sort,
            limit=limit,
            offset=offset,
        )
        return ReferencePageResponse(
            items=[reference_response(record) for record in records],
            total=total,
            limit=limit,
            offset=offset,
        )

    @application.get(
        "/references/{reference_id}",
        response_model=ReferenceResponse,
        responses={
            **AUTHENTICATION_REQUIRED_RESPONSES,
            404: {"model": ErrorResponse},
        },
    )
    def get_reference(
        reference_id: uuid.UUID,
        session: SessionDependency,
        _authenticated: AuthenticatedSessionDependency,
    ) -> ReferenceResponse:
        return reference_response(library.get(session, reference_id))

    @application.post(
        "/references",
        status_code=201,
        response_model=RegisterReferencesResponse,
        responses={
            **REQUEST_VALIDATION_RESPONSES,
            **AUTHENTICATED_WRITE_RESPONSES,
            409: {"model": ErrorResponse},
        },
    )
    def register_references(
        request: RegisterReferencesRequest,
        session: SessionDependency,
        authenticated: WriteSessionDependency,
    ) -> RegisterReferencesResponse:
        with write_transaction(session):
            records = library.register(
                session,
                bibtex=request.bibtex,
                source=request.source,
                policy=selected_registration_policy,
                actor_user_id=authenticated.user.id,
                citation_contexts=request.citation_contexts,
                venue_registry=configuration.venue_registry(session),
            )
        responses = [reference_response(record) for record in records]
        return RegisterReferencesResponse(
            reference=responses[0], references=responses
        )

    @application.put(
        "/references/{reference_id}",
        response_model=ReferenceResponse,
        responses={
            **REQUEST_VALIDATION_RESPONSES,
            **AUTHENTICATED_WRITE_RESPONSES,
            404: {"model": ErrorResponse},
            409: {"model": ErrorResponse},
        },
    )
    def update_reference(
        reference_id: uuid.UUID,
        request: UpdateReferenceRequest,
        session: SessionDependency,
        authenticated: WriteSessionDependency,
    ) -> ReferenceResponse:
        with write_transaction(session):
            record = library.update(
                session,
                reference_id=reference_id,
                bibtex=request.bibtex,
                source_revision=request.source_revision,
                policy=selected_registration_policy,
                actor_user_id=authenticated.user.id,
                venue_registry=configuration.venue_registry(session),
            )
        return reference_response(record)

    @application.post(
        "/references/{reference_id}/citation-contexts",
        response_model=ReferenceResponse,
        responses={
            **REQUEST_VALIDATION_RESPONSES,
            **AUTHENTICATED_WRITE_RESPONSES,
            404: {"model": ErrorResponse},
        },
    )
    def add_reference_citation_contexts(
        reference_id: uuid.UUID,
        request: AddCitationContextsRequest,
        session: SessionDependency,
        authenticated: WriteSessionDependency,
    ) -> ReferenceResponse:
        with write_transaction(session):
            record = library.add_citation_contexts(
                session,
                reference_id=reference_id,
                contexts=request.contexts,
                actor_user_id=authenticated.user.id,
            )
        return reference_response(record)

    @application.delete(
        "/references/{reference_id}",
        status_code=204,
        responses={
            **AUTHENTICATED_WRITE_RESPONSES,
            404: {"model": ErrorResponse},
        },
    )
    def delete_reference(
        reference_id: uuid.UUID,
        session: SessionDependency,
        authenticated: WriteSessionDependency,
        if_match: Annotated[str, Header(alias="If-Match")],
    ) -> Response:
        expected_revision = if_match.strip()
        if (
            len(expected_revision) >= 2
            and expected_revision[0] == expected_revision[-1] == '"'
        ):
            expected_revision = expected_revision[1:-1]
        with write_transaction(session):
            library.delete(
                session,
                reference_id=reference_id,
                expected_source_revision=expected_revision,
                actor_user_id=authenticated.user.id,
            )
        return Response(status_code=204)

    return application


def _request_id(candidate: str | None) -> str:
    if (
        candidate
        and len(candidate) <= 128
        and all(character.isalnum() or character in "._:-" for character in candidate)
    ):
        return candidate
    return str(uuid.uuid4())


def _metric_labels(**labels: str) -> str:
    return ",".join(
        f'{name}="{_escape_metric_label(value)}"'
        for name, value in labels.items()
    )


def _escape_metric_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


app = create_app()

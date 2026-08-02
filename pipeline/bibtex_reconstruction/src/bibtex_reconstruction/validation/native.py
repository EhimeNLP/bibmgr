"""Thin adapter around the public bibmgr-native registration API."""

from __future__ import annotations

from typing import Any

from ..domain import RustValidationResult, ValidationDiagnostic


class NativeValidationUnavailable(RuntimeError):
    """Raised when the PR #19 native extension is not installed."""


class NativeBibtexValidator:
    """Validate candidates without rewriting their source representation."""

    def validate(self, source: str) -> RustValidationResult:
        try:
            import bibmgr_native
        except ImportError as exc:
            raise NativeValidationUnavailable(
                "bibmgr_native is unavailable; run `uv sync --project "
                "pipeline/bibtex_reconstruction --group dev` from the repository root"
            ) from exc

        decision = bibmgr_native.validate_for_registration(
            source,
            policy="modern",
        )

        diagnostics = [
            self._diagnostic_from_native(diagnostic)
            for diagnostic in decision.diagnostics
        ]
        return RustValidationResult(
            accepted=decision.accepted,
            source=decision.source,
            unresolved_semantics=decision.unresolved_semantics,
            diagnostics=diagnostics,
            applied_fix_ids=[],
        )

    @staticmethod
    def _diagnostic_from_native(diagnostic: Any) -> ValidationDiagnostic:
        data = diagnostic.to_dict()
        diagnostic_range = data.get("range")
        if diagnostic_range is not None:
            diagnostic_range = tuple(diagnostic_range)
        return ValidationDiagnostic(
            code=str(data.get("code", "unknown")),
            severity=str(data.get("severity", "error")),
            blocking=bool(data.get("blocking", False)),
            message=str(data.get("message", "")),
            range=diagnostic_range,
            notes=[str(note) for note in data.get("notes", [])],
            fixes=[str(fix) for fix in data.get("fixes", [])],
        )

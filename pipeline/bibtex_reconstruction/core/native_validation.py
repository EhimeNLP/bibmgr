"""Thin adapter around the public bibmgr-native registration API."""

from __future__ import annotations

from typing import Any

from core.candidate_normalization import normalize_candidate_source
from core.config import settings
from models import RustValidationResult, ValidationDiagnostic


class NativeValidationUnavailable(RuntimeError):
    """Raised when the PR #19 native extension is not installed."""


class NativeBibtexValidator:
    """Normalize candidates, apply allowed Rust fixes, and make the final decision."""

    def __init__(self, policy: str = "laboratory") -> None:
        self.policy = policy

    def validate(self, source: str) -> RustValidationResult:
        try:
            import bibmgr_native
        except ImportError as exc:
            raise NativeValidationUnavailable(
                "bibmgr_native is unavailable; run `uv sync --project "
                "pipeline/bibtex_reconstruction --group dev` from the repository root"
            ) from exc

        normalized = normalize_candidate_source(source)
        applied_fix_ids: list[str] = []

        safe_fix_result = bibmgr_native.apply_fixes(
            normalized,
            profile=self.policy,
        )
        normalized = safe_fix_result.source
        applied_fix_ids.extend(safe_fix_result.applied_fix_ids)

        decision = bibmgr_native.validate_for_registration(
            normalized,
            policy=self.policy,
        )
        if not decision.accepted and settings.rewrite_citation_keys:
            key_fix_ids = [
                diagnostic.fixes[0]
                for diagnostic in decision.diagnostics
                if (
                    diagnostic.blocking
                    and diagnostic.code == "LAB-KEY-002"
                    and diagnostic.fixes
                )
            ]
            if key_fix_ids:
                key_fix_result = bibmgr_native.apply_fixes(
                    normalized,
                    fix_ids=key_fix_ids,
                    profile=self.policy,
                    source_revision=decision.source_revision,
                )
                normalized = key_fix_result.source
                applied_fix_ids.extend(key_fix_result.applied_fix_ids)
                decision = bibmgr_native.validate_for_registration(
                    normalized,
                    policy=self.policy,
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
            applied_fix_ids=applied_fix_ids,
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

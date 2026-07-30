"""Evidence-grounded manual-review assistance using structured LLM output."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Protocol

from ..clients.llm import (
    LLMProvider,
    LLMProviderError,
    create_preferred_llm_providers,
)
from ..domain import (
    EvidenceBundle,
    LLMReviewSuggestion,
    RustValidationResult,
)


class ReviewAssistanceUnavailable(RuntimeError):
    """Raised when no configured review assistant can be invoked."""


class ReviewAssistant(Protocol):
    def reconstruct(
        self,
        evidence: EvidenceBundle,
        *,
        previous_candidate: str | None = None,
        validation: RustValidationResult | None = None,
        quality_issues: Sequence[str] = (),
    ) -> LLMReviewSuggestion:
        """Produce non-authoritative guidance for a human reviewer."""


class ConfiguredReviewAssistant:
    """Use configured LLM providers to assist one unresolved reference."""

    def __init__(self, provider: LLMProvider | None = None) -> None:
        self.providers = (
            [provider] if provider is not None else create_preferred_llm_providers()
        )

    def reconstruct(
        self,
        evidence: EvidenceBundle,
        *,
        previous_candidate: str | None = None,
        validation: RustValidationResult | None = None,
        quality_issues: Sequence[str] = (),
    ) -> LLMReviewSuggestion:
        prompt = self._build_prompt(
            evidence,
            previous_candidate=previous_candidate,
            validation=validation,
            quality_issues=quality_issues,
        )
        if not self.providers:
            raise ReviewAssistanceUnavailable(
                "no API or local vLLM review assistant is configured"
            )
        errors: list[str] = []
        for provider in self.providers:
            try:
                return provider.generate(prompt, LLMReviewSuggestion)
            except LLMProviderError as exc:
                errors.append(str(exc))
        raise ReviewAssistanceUnavailable("; ".join(errors))

    @staticmethod
    def _build_prompt(
        evidence: EvidenceBundle,
        *,
        previous_candidate: str | None,
        validation: RustValidationResult | None,
        quality_issues: Sequence[str] = (),
    ) -> str:
        diagnostics = []
        if validation:
            diagnostics = [
                {
                    "code": item.code,
                    "message": item.message,
                    "notes": item.notes,
                    "fixes": item.fixes,
                }
                for item in validation.diagnostics
                if item.blocking or item.severity == "error"
            ]

        task = {
            "output_schema": LLMReviewSuggestion.model_json_schema(),
            "evidence_bundle": evidence.model_dump(mode="json"),
            "previous_candidate": previous_candidate,
            "rust_diagnostics": diagnostics,
            "quality_issues": list(quality_issues),
        }
        return (
            "You assist a human reviewing one unresolved academic citation.\n"
            "Your response is advisory and will never be accepted automatically. "
            "Return only the required JSON object without Markdown.\n"
            "Use only facts supported by the raw input or API evidence. Never "
            "invent a DOI, author, venue, year, volume, issue, or pages. Put "
            "uncertain or conflicting fields in unresolved_fields.\n"
            "Explain candidate agreement and disagreement in candidate_assessment. "
            "Provide concise search_queries that a reviewer can verify. A "
            "suggested_bibtex value is optional and must remain evidence-grounded.\n"
            "Treat a trailing letter in an extracted year such as 2017a or "
            "2017b as a citation disambiguation label, not part of the BibTeX "
            "year value.\n"
            "If Rust diagnostics or quality_issues are present, explain what must "
            "be checked rather than claiming the record is repaired. List the "
            "source_api names actually used.\n\n"
            f"INPUT:\n{json.dumps(task, ensure_ascii=False, indent=2)}"
        )

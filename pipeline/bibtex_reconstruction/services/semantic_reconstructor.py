"""Evidence-grounded semantic reconstruction with a structured LLM response."""

from __future__ import annotations

import json
from typing import Protocol

from models import (
    EvidenceBundle,
    LLMReconstruction,
    RustValidationResult,
)
from services.llm_providers import (
    LLMProvider,
    LLMProviderError,
    create_llm_provider,
)


class SemanticReconstructionUnavailable(RuntimeError):
    """Raised when semantic reconstruction cannot be invoked."""


class SemanticReconstructor(Protocol):
    def reconstruct(
        self,
        evidence: EvidenceBundle,
        *,
        previous_candidate: str | None = None,
        validation: RustValidationResult | None = None,
    ) -> LLMReconstruction:
        """Produce one evidence-grounded BibTeX candidate."""


class ConfiguredSemanticReconstructor:
    """Use the configured LLM provider to repair one bibliographic record."""

    def __init__(self, provider: LLMProvider | None = None) -> None:
        self.provider = provider

    def reconstruct(
        self,
        evidence: EvidenceBundle,
        *,
        previous_candidate: str | None = None,
        validation: RustValidationResult | None = None,
    ) -> LLMReconstruction:
        prompt = self._build_prompt(
            evidence,
            previous_candidate=previous_candidate,
            validation=validation,
        )
        try:
            provider = self.provider or create_llm_provider()
            return provider.generate(prompt)
        except LLMProviderError as exc:
            raise SemanticReconstructionUnavailable(str(exc)) from exc

    @staticmethod
    def _build_prompt(
        evidence: EvidenceBundle,
        *,
        previous_candidate: str | None,
        validation: RustValidationResult | None,
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
            "output_schema": LLMReconstruction.model_json_schema(),
            "evidence_bundle": evidence.model_dump(mode="json"),
            "previous_candidate": previous_candidate,
            "rust_diagnostics": diagnostics,
        }
        return (
            "You reconstruct one academic BibTeX entry from damaged input and "
            "source-attributed API evidence.\n"
            "Return exactly one entry in the bibtex field of the required JSON "
            "schema. Do not wrap it in Markdown.\n"
            "Use only facts supported by the raw input or API evidence. Never "
            "invent a DOI, author, venue, year, volume, issue, or pages.\n"
            "Resolve conflicts by preferring exact identifiers, then agreement "
            "between independent sources. Preserve meaningful TeX bracing.\n"
            "Choose the bibliographic entry type from the evidence; do not force "
            "preprints into @article. Omit unsupported optional fields.\n"
            "If Rust diagnostics are present, repair the previous candidate while "
            "preserving supported information. List any unresolved fields and "
            "the source_api names actually used.\n\n"
            f"INPUT:\n{json.dumps(task, ensure_ascii=False, indent=2)}"
        )

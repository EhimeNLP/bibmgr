"""Evidence-grounded semantic reconstruction with a structured LLM response."""

from __future__ import annotations

import json
from typing import Protocol

from core.config import settings
from models import (
    EvidenceBundle,
    LLMReconstruction,
    RustValidationResult,
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


class GeminiSemanticReconstructor:
    """Use Gemini structured output to repair one bibliographic record."""

    def reconstruct(
        self,
        evidence: EvidenceBundle,
        *,
        previous_candidate: str | None = None,
        validation: RustValidationResult | None = None,
    ) -> LLMReconstruction:
        if not settings.gemini_api_key:
            raise SemanticReconstructionUnavailable(
                "GEMINI_API_KEY is not configured"
            )

        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise SemanticReconstructionUnavailable(
                "google-genai is not installed"
            ) from exc

        prompt = self._build_prompt(
            evidence,
            previous_candidate=previous_candidate,
            validation=validation,
        )
        client = genai.Client(api_key=settings.gemini_api_key)
        response = client.models.generate_content(
            model=settings.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=settings.temperature,
                max_output_tokens=settings.max_output_tokens,
                response_mime_type="application/json",
                response_schema=LLMReconstruction,
            ),
        )

        if isinstance(response.parsed, LLMReconstruction):
            return response.parsed
        if response.parsed:
            return LLMReconstruction.model_validate(response.parsed)
        if response.text:
            return LLMReconstruction.model_validate_json(response.text)
        raise SemanticReconstructionUnavailable(
            "Gemini returned no structured reconstruction"
        )

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

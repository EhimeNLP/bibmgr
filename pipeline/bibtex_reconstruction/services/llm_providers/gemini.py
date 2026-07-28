"""Gemini adapter for semantic BibTeX reconstruction."""

from __future__ import annotations

from models import LLMReconstruction

from .base import LLMProviderError


class GeminiProvider:
    """Generate structured output through the Google Gen AI SDK."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "",
        temperature: float = 0.1,
        max_output_tokens: int = 2048,
    ) -> None:
        if not api_key:
            raise LLMProviderError(
                "BIBTEX_RECONSTRUCTION_LLM_API_KEY is required for provider 'gemini'"
            )
        if not model:
            raise LLMProviderError(
                "BIBTEX_RECONSTRUCTION_LLM_MODEL is not configured"
            )

        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens

    def generate(self, prompt: str) -> LLMReconstruction:
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise LLMProviderError("google-genai is not installed") from exc

        client_options: dict[str, object] = {"api_key": self.api_key}
        if self.base_url:
            client_options["http_options"] = types.HttpOptions(
                base_url=self.base_url
            )

        try:
            client = genai.Client(**client_options)
            response = client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=self.temperature,
                    max_output_tokens=self.max_output_tokens,
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
        except Exception as exc:
            raise LLMProviderError(
                f"Gemini provider failed: {type(exc).__name__}"
            ) from exc

        raise LLMProviderError(
            "Gemini provider returned no structured reconstruction"
        )

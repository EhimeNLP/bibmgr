"""Configured LLM provider selection."""

from __future__ import annotations

from ...config import Settings, settings

from .base import LLMProvider, LLMProviderError
from .gemini import GeminiProvider
from .openai_compatible import OpenAICompatibleProvider

OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"


def create_llm_provider(
    configured_settings: Settings = settings,
) -> LLMProvider:
    """Create the provider selected by the reconstruction configuration."""

    provider = (
        configured_settings.llm_provider.strip().casefold().replace("-", "_")
    )
    if provider == "gemini":
        return GeminiProvider(
            api_key=configured_settings.llm_api_key,
            model=configured_settings.llm_model,
            base_url=configured_settings.llm_base_url,
            temperature=configured_settings.temperature,
            max_output_tokens=configured_settings.max_output_tokens,
        )
    if provider in {"openai", "openai_compatible"}:
        if provider == "openai" and not configured_settings.llm_api_key:
            raise LLMProviderError(
                "BIBTEX_RECONSTRUCTION_LLM_API_KEY is required for "
                "provider 'openai'"
            )
        base_url = configured_settings.llm_base_url
        if provider == "openai":
            base_url = base_url or OPENAI_DEFAULT_BASE_URL
        return OpenAICompatibleProvider(
            api_key=configured_settings.llm_api_key,
            model=configured_settings.llm_model,
            base_url=base_url,
            timeout=configured_settings.llm_timeout,
            use_json_schema=provider == "openai",
        )
    raise LLMProviderError(
        "Unsupported BIBTEX_RECONSTRUCTION_LLM_PROVIDER: "
        f"{configured_settings.llm_provider!r}. "
        "Choose gemini, openai, or openai_compatible."
    )


__all__ = [
    "GeminiProvider",
    "LLMProvider",
    "LLMProviderError",
    "OpenAICompatibleProvider",
    "create_llm_provider",
]

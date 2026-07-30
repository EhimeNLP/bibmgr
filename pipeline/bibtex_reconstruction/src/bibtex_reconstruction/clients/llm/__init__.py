"""Configured LLM provider selection."""

from __future__ import annotations

from ...config import Settings, settings

from .base import LLMProvider, LLMProviderError
from .gemini import GeminiProvider
from .openai_compatible import OpenAICompatibleProvider
from .vllm import VLLMProvider

OPENAI_DEFAULT_BASE_URL = "https://api.openai.com/v1"


def create_local_vllm_provider(
    configured_settings: Settings = settings,
) -> VLLMProvider:
    """Create the primary local vLLM provider."""

    if not configured_settings.local_llm_enabled:
        raise LLMProviderError(
            "BIBTEX_RECONSTRUCTION_LOCAL_LLM_ENABLED is false"
        )
    return VLLMProvider(
        api_key=configured_settings.local_llm_api_key,
        model=configured_settings.local_llm_model,
        base_url=configured_settings.local_llm_base_url,
        timeout=configured_settings.local_llm_timeout,
        temperature=configured_settings.local_llm_temperature,
        max_output_tokens=(
            configured_settings.local_llm_max_output_tokens
        ),
        seed=configured_settings.local_llm_seed,
    )


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
            strict_json_schema=provider == "openai",
            temperature=configured_settings.temperature,
            max_output_tokens=configured_settings.max_output_tokens,
        )
    raise LLMProviderError(
        "Unsupported BIBTEX_RECONSTRUCTION_LLM_PROVIDER: "
        f"{configured_settings.llm_provider!r}. "
        "Choose gemini, openai, or openai_compatible."
    )


def create_preferred_llm_providers(
    configured_settings: Settings = settings,
) -> list[LLMProvider]:
    """Return local vLLM first and opt-in remote API fallback last."""

    providers: list[LLMProvider] = []
    if (
        configured_settings.local_llm_enabled
        and configured_settings.local_llm_model
        and configured_settings.local_llm_base_url
    ):
        providers.append(create_local_vllm_provider(configured_settings))

    if not configured_settings.remote_llm_fallback_enabled:
        return providers

    provider_name = (
        configured_settings.llm_provider.strip().casefold().replace("-", "_")
    )
    remote_is_configured = (
        provider_name in {"gemini", "openai"}
        and bool(configured_settings.llm_api_key)
    ) or (
        provider_name == "openai_compatible"
        and bool(configured_settings.llm_base_url)
    )
    if remote_is_configured:
        providers.append(create_llm_provider(configured_settings))
    return providers


__all__ = [
    "GeminiProvider",
    "LLMProvider",
    "LLMProviderError",
    "OpenAICompatibleProvider",
    "VLLMProvider",
    "create_llm_provider",
    "create_local_vllm_provider",
    "create_preferred_llm_providers",
]

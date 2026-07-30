from __future__ import annotations

import json

import pytest

from bibtex_reconstruction.application.review_assistant import (
    ConfiguredReviewAssistant,
)
from bibtex_reconstruction.clients.llm import (
    GeminiProvider,
    LLMProviderError,
    OpenAICompatibleProvider,
    VLLMProvider,
    create_llm_provider,
    create_preferred_llm_providers,
)
from bibtex_reconstruction.config import Settings
from bibtex_reconstruction.domain import (
    EvidenceBundle,
    LLMReviewSuggestion,
    ReferenceData,
)


class FakeResponse:
    def __init__(self, content: str) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, object]:
        return {
            "choices": [
                {"message": {"content": self.content}},
            ]
        }


class FakeHttpClient:
    def __init__(self, content: str) -> None:
        self.response = FakeResponse(content)
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, **kwargs) -> FakeResponse:
        self.calls.append({"url": url, **kwargs})
        return self.response


class FakeProvider:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def generate(self, prompt: str, response_model):
        self.prompts.append(prompt)
        return response_model(
            suggested_bibtex="@misc{example, title = {Suggested}}",
            search_queries=["Damaged title bibliography"],
            candidate_assessment="The title is not corroborated.",
            evidence_sources=["raw input"],
        )


def reconstruction_json() -> str:
    return json.dumps(
        {
            "suggested_bibtex": "@article{example, title = {Suggested}}",
            "search_queries": ["example bibliography"],
            "candidate_assessment": "One matching source.",
            "evidence_sources": ["Crossref API"],
            "unresolved_fields": [],
            "summary": "Recovered from evidence.",
        }
    )


def test_openai_compatible_provider_uses_configured_endpoint_and_key():
    http_client = FakeHttpClient(reconstruction_json())
    provider = OpenAICompatibleProvider(
        api_key="secret",
        model="local-model",
        base_url="https://llm.example.test/v1/",
        timeout=45,
        http_client=http_client,
    )

    result = provider.generate("review this", LLMReviewSuggestion)

    assert result.candidate_assessment == "One matching source."
    call = http_client.calls[0]
    assert call["url"] == "https://llm.example.test/v1/chat/completions"
    assert call["headers"]["Authorization"] == "Bearer secret"
    assert call["json"]["model"] == "local-model"
    assert call["json"]["response_format"] == {"type": "json_object"}
    assert call["timeout"] == 45


def test_openai_compatible_provider_allows_keyless_local_server():
    http_client = FakeHttpClient(reconstruction_json())
    provider = OpenAICompatibleProvider(
        api_key="",
        model="local-model",
        base_url="http://localhost:11434/v1",
        http_client=http_client,
    )

    provider.generate("review this", LLMReviewSuggestion)

    assert "Authorization" not in http_client.calls[0]["headers"]


def test_vllm_provider_uses_deterministic_json_schema_inference():
    http_client = FakeHttpClient(reconstruction_json())
    provider = VLLMProvider(
        api_key="",
        model="Qwen/Qwen3.5-35B-A3B",
        base_url="http://127.0.0.1:8001/v1",
        http_client=http_client,
    )

    provider.generate("review this", LLMReviewSuggestion)

    payload = http_client.calls[0]["json"]
    assert payload["temperature"] == 0.0
    assert payload["seed"] == 0
    assert payload["response_format"]["type"] == "json_schema"
    assert payload["response_format"]["json_schema"]["strict"] is True
    assert payload["chat_template_kwargs"] == {
        "enable_thinking": False
    }


def test_openai_provider_defaults_to_official_endpoint_and_json_schema():
    configured = Settings(
        BIBTEX_RECONSTRUCTION_LLM_PROVIDER="openai",
        BIBTEX_RECONSTRUCTION_LLM_MODEL="gpt-test",
        BIBTEX_RECONSTRUCTION_LLM_API_KEY="secret",
    )

    provider = create_llm_provider(configured)

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.base_url == "https://api.openai.com/v1"
    assert provider.use_json_schema is True


def test_openai_compatible_provider_requires_base_url():
    configured = Settings(
        BIBTEX_RECONSTRUCTION_LLM_PROVIDER="openai_compatible",
        BIBTEX_RECONSTRUCTION_LLM_MODEL="local-model",
    )

    with pytest.raises(LLMProviderError, match="LLM_BASE_URL"):
        create_llm_provider(configured)


def test_local_vllm_is_preferred_before_opt_in_remote_fallback():
    configured = Settings(
        _env_file=None,
        BIBTEX_RECONSTRUCTION_REMOTE_LLM_FALLBACK_ENABLED=True,
        BIBTEX_RECONSTRUCTION_LLM_PROVIDER="gemini",
        BIBTEX_RECONSTRUCTION_LLM_MODEL="remote-model",
        BIBTEX_RECONSTRUCTION_LLM_API_KEY="secret",
        BIBTEX_RECONSTRUCTION_LOCAL_LLM_MODEL="local-model",
        BIBTEX_RECONSTRUCTION_LOCAL_LLM_BASE_URL=(
            "http://localhost:8001/v1"
        ),
    )

    providers = create_preferred_llm_providers(configured)

    assert isinstance(providers[0], VLLMProvider)
    assert isinstance(providers[1], GeminiProvider)
    assert providers[0].provider_label == "local_vllm"
    assert providers[1].provider_label == "api_llm"


def test_remote_api_is_disabled_by_default_even_when_key_exists():
    configured = Settings(
        _env_file=None,
        BIBTEX_RECONSTRUCTION_LLM_PROVIDER="gemini",
        BIBTEX_RECONSTRUCTION_LLM_API_KEY="secret",
    )

    providers = create_preferred_llm_providers(configured)

    assert len(providers) == 1
    assert isinstance(providers[0], VLLMProvider)


def test_unknown_provider_reports_supported_values():
    configured = Settings(
        BIBTEX_RECONSTRUCTION_LLM_PROVIDER="unknown",
        BIBTEX_RECONSTRUCTION_LLM_MODEL="model",
    )

    with pytest.raises(LLMProviderError, match="gemini, openai"):
        create_llm_provider(configured)


def test_environment_overrides_yaml_llm_settings(monkeypatch):
    monkeypatch.setenv(
        "BIBTEX_RECONSTRUCTION_LLM_PROVIDER",
        "openai_compatible",
    )
    monkeypatch.setenv(
        "BIBTEX_RECONSTRUCTION_LLM_MODEL",
        "environment-model",
    )
    monkeypatch.setenv(
        "BIBTEX_RECONSTRUCTION_LLM_API_KEY",
        "environment-key",
    )
    monkeypatch.setenv(
        "BIBTEX_RECONSTRUCTION_LLM_BASE_URL",
        "http://localhost:1234/v1",
    )

    configured = Settings()

    assert configured.llm_provider == "openai_compatible"
    assert configured.llm_model == "environment-model"
    assert configured.llm_api_key == "environment-key"
    assert configured.llm_base_url == "http://localhost:1234/v1"


def test_review_assistant_builds_provider_independent_prompt():
    provider = FakeProvider()
    reference = ReferenceData(
        id="ref-1",
        title="Damaged title",
        raw_text="@article{broken",
    )
    evidence = EvidenceBundle(
        raw_text=reference.raw_text,
        original=reference,
        search_clues=reference,
    )
    assistant = ConfiguredReviewAssistant(provider)

    result = assistant.reconstruct(
        evidence,
        quality_issues=["title", "year"],
    )

    assert result.suggested_bibtex is not None
    assert "Damaged title" in provider.prompts[0]
    assert '"output_schema"' in provider.prompts[0]
    assert '"search_queries"' in provider.prompts[0]
    assert '"quality_issues": [' in provider.prompts[0]
    assert '"title"' in provider.prompts[0]
    assert '"year"' in provider.prompts[0]

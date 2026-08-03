from __future__ import annotations

import json

import pytest

from bibtex_reconstruction.application.query_improvement import (
    ConfiguredQueryImprover,
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
    ReferenceData,
    SearchQueryResponse,
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
        return response_model(queries=["Damaged title bibliography"])


def reconstruction_json() -> str:
    return json.dumps({"queries": ["example bibliography"]})


def test_openai_compatible_provider_uses_configured_endpoint_and_key():
    http_client = FakeHttpClient(reconstruction_json())
    provider = OpenAICompatibleProvider(
        api_key="secret",
        model="local-model",
        base_url="https://llm.example.test/v1/",
        timeout=45,
        http_client=http_client,
    )

    result = provider.generate("review this", SearchQueryResponse)

    assert result.queries == ["example bibliography"]
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

    provider.generate("review this", SearchQueryResponse)

    assert "Authorization" not in http_client.calls[0]["headers"]


def test_vllm_provider_uses_deterministic_json_schema_inference():
    http_client = FakeHttpClient(reconstruction_json())
    provider = VLLMProvider(
        api_key="",
        model="Qwen/Qwen3.6-27B",
        base_url="http://127.0.0.1:8001/v1",
        http_client=http_client,
    )

    provider.generate("review this", SearchQueryResponse)

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
        llm_provider="openai",
        llm_model="gpt-test",
        llm_api_key="secret",
    )

    provider = create_llm_provider(configured)

    assert isinstance(provider, OpenAICompatibleProvider)
    assert provider.base_url == "https://api.openai.com/v1"
    assert provider.use_json_schema is True


def test_openai_compatible_provider_requires_base_url():
    configured = Settings(
        llm_provider="openai_compatible",
        llm_model="local-model",
    )

    with pytest.raises(LLMProviderError, match="LLM_BASE_URL"):
        create_llm_provider(configured)


def test_local_vllm_is_preferred_before_opt_in_remote_fallback():
    configured = Settings(
        _env_file=None,
        remote_llm_fallback_enabled=True,
        llm_provider="gemini",
        llm_model="remote-model",
        llm_api_key="secret",
        local_llm_model="local-model",
        local_llm_base_url="http://localhost:8001/v1",
    )

    providers = create_preferred_llm_providers(configured)

    assert isinstance(providers[0], VLLMProvider)
    assert isinstance(providers[1], GeminiProvider)
    assert providers[0].provider_label == "local_vllm"
    assert providers[1].provider_label == "api_llm"


def test_remote_api_is_disabled_by_default_even_when_key_exists():
    configured = Settings(
        _env_file=None,
        llm_provider="gemini",
        llm_api_key="secret",
    )

    providers = create_preferred_llm_providers(configured)

    assert len(providers) == 1
    assert isinstance(providers[0], VLLMProvider)


def test_unknown_provider_reports_supported_values():
    configured = Settings(
        llm_provider="unknown",
        llm_model="model",
    )

    with pytest.raises(LLMProviderError, match="gemini, openai"):
        create_llm_provider(configured)


def test_process_environment_overrides_toml_llm_settings(monkeypatch):
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


def test_query_improver_uses_all_citation_evidence_and_model_knowledge():
    provider = FakeProvider()
    reference = ReferenceData(
        id="ref-1",
        title="Damaged title",
        authors=["Ada Example"],
        year="2024",
        venue="Example Conference",
        raw_text="Ada Example. Damaged title. Example Conference, 2024.",
    )
    assistant = ConfiguredQueryImprover([provider])
    result = assistant.improve(reference)

    assert result.queries == ["Damaged title bibliography"]
    prompt = provider.prompts[0]
    assert "Damaged title" in prompt
    assert "Ada Example" in prompt
    assert "Example Conference" in prompt
    assert "raw citation" in prompt
    assert "learned knowledge" in prompt
    assert "known DOI may be placed in a query" in prompt
    assert "likely original language" in prompt
    assert "BibTeX" in provider.prompts[0]
    assert result.invocation.task.value == "query_improvement"

from __future__ import annotations

import json

import pytest

from bibtex_reconstruction.application.semantic_reconstructor import (
    ConfiguredSemanticReconstructor,
)
from bibtex_reconstruction.clients.llm import (
    LLMProviderError,
    OpenAICompatibleProvider,
    create_llm_provider,
)
from bibtex_reconstruction.config import Settings
from bibtex_reconstruction.domain import (
    EvidenceBundle,
    LLMReconstruction,
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

    def generate(self, prompt: str) -> LLMReconstruction:
        self.prompts.append(prompt)
        return LLMReconstruction(
            bibtex="@misc{example, title = {Recovered}}",
            confidence=0.8,
            evidence_sources=["raw input"],
        )


def reconstruction_json() -> str:
    return json.dumps(
        {
            "bibtex": "@article{example, title = {Recovered}}",
            "confidence": 0.9,
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

    result = provider.generate("reconstruct this")

    assert result.confidence == 0.9
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

    provider.generate("reconstruct this")

    assert "Authorization" not in http_client.calls[0]["headers"]


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


def test_semantic_reconstructor_builds_provider_independent_prompt():
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
    reconstructor = ConfiguredSemanticReconstructor(provider)

    result = reconstructor.reconstruct(evidence)

    assert result.confidence == 0.8
    assert "Damaged title" in provider.prompts[0]
    assert '"output_schema"' in provider.prompts[0]
    assert '"unresolved_fields"' in provider.prompts[0]

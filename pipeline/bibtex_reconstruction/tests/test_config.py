import pytest
from pydantic import ValidationError

from bibtex_reconstruction.config import Settings


def test_settings_defaults_are_valid_without_yaml(monkeypatch):
    for name in (
        "BIBTEX_RECONSTRUCTION_SIMILARITY_THRESHOLD",
        "BIBTEX_RECONSTRUCTION_MAX_RETRIES",
        "BIBTEX_RECONSTRUCTION_ARXIV_WAIT_SEC",
        "BIBTEX_RECONSTRUCTION_REFERENCE_THREADS",
        "BIBTEX_RECONSTRUCTION_API_THREADS",
        "BIBTEX_RECONSTRUCTION_LLM_PROVIDER",
        "BIBTEX_RECONSTRUCTION_LLM_MODEL",
        "BIBTEX_RECONSTRUCTION_LOCAL_LLM_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)

    configured = Settings(_env_file=None)

    assert configured.similarity_threshold == 0.95
    assert configured.max_retries == 2
    assert configured.reference_threads == 2
    assert configured.api_threads == 3
    assert configured.arxiv_wait_sec == 3
    assert configured.local_llm_enabled is True
    assert configured.local_llm_model == "Qwen/Qwen3-32B-AWQ"
    assert configured.local_llm_base_url == "http://127.0.0.1:8001/v1"
    assert configured.local_llm_temperature == 0.0
    assert configured.remote_llm_fallback_enabled is False
    assert configured.llm_provider == "gemini"
    assert configured.llm_model


def test_prefixed_environment_overrides_runtime_tuning(monkeypatch):
    monkeypatch.setenv(
        "BIBTEX_RECONSTRUCTION_SIMILARITY_THRESHOLD",
        "0.98",
    )
    monkeypatch.setenv(
        "BIBTEX_RECONSTRUCTION_REFERENCE_THREADS",
        "4",
    )
    monkeypatch.setenv(
        "BIBTEX_RECONSTRUCTION_API_THREADS",
        "2",
    )
    monkeypatch.setenv(
        "BIBTEX_RECONSTRUCTION_LOCAL_LLM_TIMEOUT",
        "45",
    )

    configured = Settings(_env_file=None)

    assert configured.similarity_threshold == 0.98
    assert configured.reference_threads == 4
    assert configured.api_threads == 2
    assert configured.local_llm_timeout == 45


def test_invalid_environment_value_fails_at_startup(monkeypatch):
    monkeypatch.setenv(
        "BIBTEX_RECONSTRUCTION_SIMILARITY_THRESHOLD",
        "1.5",
    )

    with pytest.raises(ValidationError):
        Settings(_env_file=None)

import pytest
from pydantic import ValidationError

from bibtex_reconstruction.config import Settings


def test_settings_defaults_are_valid_without_yaml(monkeypatch):
    for name in (
        "BIBTEX_RECONSTRUCTION_SIMILARITY_THRESHOLD",
        "BIBTEX_RECONSTRUCTION_MAX_RETRIES",
        "BIBTEX_RECONSTRUCTION_ARXIV_WAIT_SEC",
        "BIBTEX_RECONSTRUCTION_LLM_PROVIDER",
        "BIBTEX_RECONSTRUCTION_LLM_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)

    configured = Settings(_env_file=None)

    assert configured.similarity_threshold == 0.95
    assert configured.max_retries == 2
    assert configured.arxiv_wait_sec == 1
    assert configured.llm_provider == "gemini"
    assert configured.llm_model


def test_prefixed_environment_overrides_runtime_tuning(monkeypatch):
    monkeypatch.setenv(
        "BIBTEX_RECONSTRUCTION_SIMILARITY_THRESHOLD",
        "0.98",
    )
    monkeypatch.setenv(
        "BIBTEX_RECONSTRUCTION_MAX_PARALLEL_REQUESTS",
        "8",
    )
    monkeypatch.setenv(
        "BIBTEX_RECONSTRUCTION_LLM_MAX_ATTEMPTS",
        "5",
    )

    configured = Settings(_env_file=None)

    assert configured.similarity_threshold == 0.98
    assert configured.max_parallel_requests == 8
    assert configured.max_llm_attempts == 5


def test_invalid_environment_value_fails_at_startup(monkeypatch):
    monkeypatch.setenv(
        "BIBTEX_RECONSTRUCTION_SIMILARITY_THRESHOLD",
        "1.5",
    )

    with pytest.raises(ValidationError):
        Settings(_env_file=None)

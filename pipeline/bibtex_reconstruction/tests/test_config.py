import pytest
from pydantic import ValidationError

import bibtex_reconstruction.config as config_module
from bibtex_reconstruction.config import Settings


def test_project_toml_settings_are_valid(monkeypatch):
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

    assert configured.similarity_threshold == 0.80
    assert configured.trusted_doi_threshold == 0.80
    assert configured.direct_bibtex_threshold == 0.90
    assert configured.max_retries == 2
    assert configured.reference_threads == 2
    assert configured.api_threads == 3
    assert configured.arxiv_wait_sec == 3
    assert configured.arxiv_timeout == 30
    assert configured.arxiv_max_retries == 3
    assert configured.semanticscholar_wait_sec == 5
    assert configured.semanticscholar_max_retries == 4
    assert configured.acl_anthology_cache_max_age_hours == 168
    assert configured.cinii_result_count == 10
    assert configured.cinii_detail_candidate_count == 3
    assert configured.local_llm_enabled is True
    assert configured.local_llm_model == "Qwen/Qwen3.6-27B"
    assert configured.local_llm_base_url == "http://127.0.0.1:8001/v1"
    assert configured.local_llm_temperature == 0.0
    assert configured.localdb_timeout == 5
    assert configured.remote_llm_fallback_enabled is False
    assert configured.llm_provider == "gemini"
    assert configured.llm_model


def test_process_environment_can_override_runtime_tuning(monkeypatch):
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


def test_dotenv_ignores_parameters_and_loads_only_secrets(
    tmp_path,
    monkeypatch,
):
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        'local_llm_model = "toml-model"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "CONFIG_PATH", toml_path)

    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "\n".join(
            (
                "BIBTEX_RECONSTRUCTION_LLM_PROVIDER=openai",
                "BIBTEX_RECONSTRUCTION_LOCAL_LLM_MODEL=ignored-model",
                "BIBTEX_RECONSTRUCTION_LLM_API_KEY=secret",
            )
        ),
        encoding="utf-8",
    )

    configured = Settings(_env_file=dotenv_path)

    assert configured.llm_provider == "gemini"
    assert configured.local_llm_model == "toml-model"
    assert configured.llm_api_key == "secret"


def test_invalid_environment_value_fails_at_startup(monkeypatch):
    monkeypatch.setenv(
        "BIBTEX_RECONSTRUCTION_SIMILARITY_THRESHOLD",
        "1.5",
    )

    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_unknown_toml_setting_fails_at_startup(tmp_path, monkeypatch):
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        "similarity_threshod = 0.7\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "CONFIG_PATH", toml_path)

    with pytest.raises(ValidationError) as raised:
        Settings(_env_file=None)

    errors = raised.value.errors()
    assert any(
        error["type"] == "extra_forbidden"
        and error["loc"] == ("similarity_threshod",)
        for error in errors
    )


def test_local_db_timeout_must_be_positive():
    with pytest.raises(ValidationError):
        Settings(localdb_timeout=0, _env_file=None)

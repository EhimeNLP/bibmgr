"""Typed runtime settings loaded from TOML and secret environment values."""

from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

PROJECT_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_DIR / ".env"
CONFIG_PATH = PROJECT_DIR / "config.toml"

DOTENV_SECRET_KEYS = frozenset(
    {
        "BIBTEX_RECONSTRUCTION_LLM_API_KEY",
        "BIBTEX_RECONSTRUCTION_LOCAL_LLM_API_KEY",
        "BIBTEX_RECONSTRUCTION_LOCAL_DB_COOKIE",
        "CINII_APPID",
        "CROSSREF_MAILTO",
        "SEMANTIC_SCHOLAR_API_KEY",
    }
)


class Settings(BaseSettings):
    """Configuration for the standalone reconstruction CLI."""

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[Any, ...]:
        def secret_dotenv_settings() -> dict[str, Any]:
            return {
                key: value
                for key, value in dotenv_settings().items()
                if key in DOTENV_SECRET_KEYS
            }

        return (
            init_settings,
            env_settings,
            secret_dotenv_settings,
            TomlConfigSettingsSource(settings_cls, toml_file=CONFIG_PATH),
            file_secret_settings,
        )

    # Search
    similarity_threshold: float = Field(0.80, ge=0.0, le=1.0)
    trusted_doi_threshold: float = Field(0.80, ge=0.0, le=1.0)
    direct_bibtex_threshold: float = Field(0.90, ge=0.0, le=1.0)
    reference_threads: int = Field(2, ge=1)
    api_threads: int = Field(3, ge=1)

    # Optional remote LLM used only as an explicitly enabled final fallback
    remote_llm_fallback_enabled: bool = False
    llm_provider: str = "gemini"
    llm_model: str = "gemini-flash-lite-latest"
    llm_api_key: str = Field("", validation_alias="BIBTEX_RECONSTRUCTION_LLM_API_KEY")
    llm_base_url: str = ""
    temperature: float = Field(0.1, ge=0.0)
    max_output_tokens: int = Field(2048, ge=1)
    llm_timeout: int = Field(120, ge=1)

    # Primary local open-source model served through vLLM
    local_llm_enabled: bool = True
    local_llm_model: str = "Qwen/Qwen3.6-27B"
    local_llm_base_url: str = "http://127.0.0.1:8001/v1"
    local_llm_api_key: str = Field("", validation_alias="BIBTEX_RECONSTRUCTION_LOCAL_LLM_API_KEY")
    local_llm_timeout: int = Field(120, ge=1)
    local_llm_temperature: float = Field(0.0, ge=0.0)
    local_llm_max_output_tokens: int = Field(2048, ge=1)
    local_llm_seed: int = Field(0, ge=0)
    concept_generation_batch_size: int = Field(32, ge=1)
    query_improvement_enabled: bool = True
    query_improvement_max_queries: int = Field(3, ge=1, le=10)
    query_improvement_max_rounds: int = Field(1, ge=0, le=3)

    # Optional BibMgR reference-library lookup
    localdb_enabled: bool = False
    localdb_base_url: str = "http://127.0.0.1:8000/references/page"
    localdb_timeout: int = Field(5, ge=1)
    localdb_cookie: str = Field("", validation_alias="BIBTEX_RECONSTRUCTION_LOCAL_DB_COOKIE")

    # Shared API behavior
    max_retries: int = Field(2, ge=1)
    retry_backoff_sec: int = Field(2, ge=1)
    doi_base_url: str = "https://doi.org/"
    doi_timeout: int = Field(15, ge=1)
    doi_wait_sec: float = Field(0.1, ge=0)
    doi_max_bytes: int = Field(2_000_000, ge=1)
    doi_max_redirects: int = Field(5, ge=0)

    # Official citation export discovered from DOI landing pages
    citation_site_timeout: int = Field(15, ge=1)
    citation_site_wait_sec: float = Field(0.5, ge=0)
    citation_site_max_bytes: int = Field(2_000_000, ge=1)
    citation_site_max_links: int = Field(5, ge=1)
    citation_site_max_redirects: int = Field(5, ge=0)

    # Crossref
    crossref_base_url: str = "https://api.crossref.org/works"
    crossref_timeout: int = Field(10, ge=1)
    crossref_wait_sec: float = Field(1.0, ge=0)
    crossref_mailto: str = Field("", validation_alias="CROSSREF_MAILTO")

    # ACL Anthology authoritative bibliography cache
    acl_anthology_base_url: str = "https://aclanthology.org"
    acl_anthology_bibtex_url: str = "https://aclanthology.org/anthology.bib.gz"
    acl_anthology_cache_path: Path = Path("data/cache/acl-anthology.bib")
    acl_anthology_cache_max_age_hours: int = Field(168, ge=0)
    acl_anthology_timeout: int = Field(120, ge=1)
    acl_anthology_wait_sec: float = Field(0.5, ge=0)

    # CiNii
    cinii_base_url: str = "https://cir.nii.ac.jp/opensearch/v2"
    cinii_timeout: int = Field(10, ge=1)
    cinii_wait_sec: float = Field(1.0, ge=0)
    cinii_result_count: int = Field(10, ge=1, le=200)
    cinii_detail_candidate_count: int = Field(3, ge=1, le=20)
    cinii_appid: str = Field("", validation_alias="CINII_APPID")

    # Semantic Scholar
    semanticscholar_base_url: str = "https://api.semanticscholar.org/graph/v1/paper/search"
    semanticscholar_timeout: int = Field(20, ge=1)
    semanticscholar_wait_sec: float = Field(5, ge=0)
    semanticscholar_max_retries: int = Field(4, ge=1)
    semanticscholar_api_key: str = Field("", validation_alias="SEMANTIC_SCHOLAR_API_KEY")

    # J-STAGE
    jstage_base_url: str = "https://api.jstage.jst.go.jp/searchapi/do"
    jstage_timeout: int = Field(10, ge=1)
    jstage_wait_sec: float = Field(0.5, ge=0)

    # arXiv
    arxiv_base_url: str = "https://export.arxiv.org/api/query"
    arxiv_bibtex_base_url: str = "https://arxiv.org/bibtex"
    arxiv_timeout: int = Field(30, ge=1)
    arxiv_wait_sec: float = Field(3.0, ge=0)
    arxiv_max_retries: int = Field(3, ge=1)

    model_config = SettingsConfigDict(
        env_file=ENV_PATH,
        env_file_encoding="utf-8",
        env_prefix="BIBTEX_RECONSTRUCTION_",
        populate_by_name=True,
        extra="forbid",
    )


settings = Settings()

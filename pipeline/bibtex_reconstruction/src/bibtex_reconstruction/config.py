"""Typed runtime settings loaded from defaults and environment variables."""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_DIR = Path(__file__).resolve().parents[2]
ENV_PATH = PROJECT_DIR / ".env"


class Settings(BaseSettings):
    """Configuration for the standalone reconstruction CLI."""

    # Search
    similarity_threshold: float = Field(0.95, ge=0.0, le=1.0)
    trusted_doi_threshold: float = Field(0.97, ge=0.0, le=1.0)
    reference_threads: int = Field(2, ge=1)
    api_threads: int = Field(3, ge=1)

    # Semantic reconstruction LLM
    llm_provider: str = Field(
        "gemini",
        validation_alias="BIBTEX_RECONSTRUCTION_LLM_PROVIDER",
    )
    llm_model: str = Field(
        "gemini-2.5-pro",
        validation_alias="BIBTEX_RECONSTRUCTION_LLM_MODEL",
    )
    llm_api_key: str = Field(
        "",
        validation_alias="BIBTEX_RECONSTRUCTION_LLM_API_KEY",
    )
    llm_base_url: str = Field(
        "",
        validation_alias="BIBTEX_RECONSTRUCTION_LLM_BASE_URL",
    )
    temperature: float = Field(
        0.1,
        ge=0.0,
        validation_alias="BIBTEX_RECONSTRUCTION_LLM_TEMPERATURE",
    )
    max_output_tokens: int = Field(
        2048,
        ge=1,
        validation_alias="BIBTEX_RECONSTRUCTION_LLM_MAX_OUTPUT_TOKENS",
    )
    max_llm_attempts: int = Field(
        3,
        ge=1,
        validation_alias="BIBTEX_RECONSTRUCTION_LLM_MAX_ATTEMPTS",
    )
    llm_timeout: int = Field(
        120,
        ge=1,
        validation_alias="BIBTEX_RECONSTRUCTION_LLM_TIMEOUT",
    )

    # Shared API behavior
    max_retries: int = Field(2, ge=1)
    retry_backoff_sec: int = Field(2, ge=1)
    doi_base_url: str = "https://doi.org/"
    doi_timeout: int = Field(15, ge=1)
    doi_wait_sec: float = Field(0.1, ge=0)

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
    crossref_mailto: str = Field(
        "",
        validation_alias="CROSSREF_MAILTO",
    )

    # CiNii
    cinii_base_url: str = "https://cir.nii.ac.jp/opensearch/v2"
    cinii_timeout: int = Field(10, ge=1)
    cinii_wait_sec: float = Field(1.0, ge=0)
    cinii_appid: str = Field(
        "",
        validation_alias="CINII_APPID",
    )

    # Semantic Scholar
    semanticscholar_base_url: str = (
        "https://api.semanticscholar.org/graph/v1/paper/search"
    )
    semanticscholar_timeout: int = Field(10, ge=1)
    semanticscholar_wait_sec: float = Field(1, ge=0)
    semanticscholar_api_key: str = Field(
        "",
        validation_alias="SEMANTIC_SCHOLAR_API_KEY",
    )

    # J-STAGE
    jstage_base_url: str = "https://api.jstage.jst.go.jp/searchapi/do"
    jstage_timeout: int = Field(10, ge=1)
    jstage_wait_sec: float = Field(0.5, ge=0)

    # arXiv
    arxiv_base_url: str = "https://export.arxiv.org/api/query"
    arxiv_bibtex_base_url: str = "https://arxiv.org/bibtex"
    arxiv_timeout: int = Field(10, ge=1)
    arxiv_wait_sec: float = Field(3.0, ge=0)

    model_config = SettingsConfigDict(
        env_file=ENV_PATH,
        env_file_encoding="utf-8",
        env_prefix="BIBTEX_RECONSTRUCTION_",
        populate_by_name=True,
        extra="ignore",
    )


settings = Settings()

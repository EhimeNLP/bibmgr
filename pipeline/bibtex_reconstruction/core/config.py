import os
import yaml
from pathlib import Path
from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.yml"
ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH)

class Settings(BaseSettings):
    # --- Search Settings ---
    similarity_threshold: float = 0.9
    trusted_doi_threshold: float = 0.97
    max_parallel_requests: int = 5
    # --- LLM Settings ---
    llm_provider: str = Field(
        "",
        validation_alias="BIBTEX_RECONSTRUCTION_LLM_PROVIDER",
    )
    llm_model: str = Field(
        "",
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
    temperature: float = 0.1
    max_output_tokens: int = 2048
    max_llm_attempts: int = 3
    llm_timeout: int = 120
    # --- Rust validation ---
    registration_policy: str = "laboratory"
    rewrite_citation_keys: bool = True
    # --- API Base URLs ---
    max_retries: int = 3
    retry_backoff_sec: int = 2
    doi_base_url: str = "https://doi.org/"
    doi_timeout: int = 15
    ## --- crossref ---
    crossref_base_url: str = "https://api.crossref.org/works"
    crossref_timeout: int = 10
    crossref_wait_sec: float = 0
    crossref_mailto: str = Field("", validation_alias="CROSSREF_MAILTO")
    ## --- cinii ---
    cinii_base_url: str = "https://cir.nii.ac.jp/opensearch/v2"
    cinii_timeout: int = 10
    cinii_wait_sec: float = 0.5
    cinii_appid: str = Field("", validation_alias="CINII_APPID")
    ## --- semanticscholar ---
    semanticscholar_base_url: str = "https://api.semanticscholar.org/graph/v1/paper/search"
    semanticscholar_timeout: int = 10
    semanticscholar_wait_sec: float = 1
    semanticscholar_api_key: str = Field("", validation_alias="SEMANTIC_SCHOLAR_API_KEY")
    ## --- jstage ---
    jstage_base_url: str = "https://api.jstage.jst.go.jp/searchapi/do"
    jstage_timeout: int = 10
    jstage_wait_sec: float = 0
    ## --- arxiv ---
    arxiv_base_url: str = "https://export.arxiv.org/api/query"
    arxiv_bibtex_base_url: str = "https://arxiv.org/bibtex"
    arxiv_timeout: int = 10
    arxiv_wait_sec: float = 0
    model_config = SettingsConfigDict(
        env_file=ENV_PATH,
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @classmethod
    def load_settings(cls):
        conf_data = {}
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                raw_data = yaml.safe_load(f) or {}
                conf_data.update(raw_data.get("search", {}))
                llm_data = raw_data.get("llm", {})
                conf_data.update({
                    "llm_provider": llm_data.get("provider"),
                    "llm_model": llm_data.get("model"),
                    "llm_base_url": llm_data.get("base_url"),
                    "temperature": llm_data.get("temperature"),
                    "max_output_tokens": llm_data.get("max_output_tokens"),
                    "max_llm_attempts": llm_data.get("max_llm_attempts"),
                    "llm_timeout": llm_data.get("timeout"),
                })
                conf_data.update(raw_data.get("validation", {}))
                
                api_section = raw_data.get("api", {})
                conf_data["max_retries"] = api_section.get("max_retries", 3)
                conf_data["retry_backoff_sec"] = api_section.get("retry_backoff_sec", 2)
                conf_data["doi_base_url"] = api_section.get("doi_base_url")
                conf_data["doi_timeout"] = api_section.get("doi_timeout", 15)
                if isinstance(api_section, dict):
                    for service in ["crossref", "cinii", "semanticscholar", "jstage", "arxiv"]:
                        detail = api_section.get(service, {})
                        conf_data[f"{service}_base_url"] = detail.get("base_url")
                        conf_data[f"{service}_timeout"] = detail.get("timeout", 10)
                        conf_data[f"{service}_wait_sec"] = detail.get("wait_sec", 0)
                    conf_data["arxiv_bibtex_base_url"] = api_section.get(
                        "arxiv",
                        {},
                    ).get("bibtex_base_url")

        environment_names = {
            "llm_provider": "BIBTEX_RECONSTRUCTION_LLM_PROVIDER",
            "llm_model": "BIBTEX_RECONSTRUCTION_LLM_MODEL",
            "llm_api_key": "BIBTEX_RECONSTRUCTION_LLM_API_KEY",
            "llm_base_url": "BIBTEX_RECONSTRUCTION_LLM_BASE_URL",
        }
        for field_name, environment_name in environment_names.items():
            if environment_name in os.environ:
                conf_data[field_name] = os.environ[environment_name]

        return cls(**{k: v for k, v in conf_data.items() if v is not None})

settings = Settings.load_settings()

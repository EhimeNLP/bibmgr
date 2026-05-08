import yaml
from pathlib import Path
from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.yml"

class Settings(BaseSettings):
    # --- Search Settings ---
    similarity_threshold: float = 0.95
    max_parallel_requests: int = 5
    # --- LLM Settings ---
    model_name: str = "gemini-flash-lite-latest"
    gemini_api_key: str = Field("", validation_alias="GEMINI_API_KEY")
    temperature: float = 0.0
    max_output_tokens: int = 150
    # --- API Base URLs ---
    max_retries: int = 3
    retry_backoff_sec: int = 2
    doi_base_url: str = "https://doi.org/"
    dblp_venue_api_url: str = "https://dblp.org/search/venue/api"
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
    arxiv_base_url: str = "http://export.arxiv.org/api/query"
    arxiv_timeout: int = 10
    arxiv_wait_sec: float = 0
    ## --- localdb ---
    localdb_enabled: bool = False
    # --- venue abbreviations ---
    venue_abbrev_map: dict[str, str] = Field(default_factory=dict)
    # --- API Keys / Environment Variables ---

    model_config = SettingsConfigDict(
        env_file=".env",
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
                conf_data.update(raw_data.get("llm", {}))
                
                api_section = raw_data.get("api", {})
                conf_data["max_retries"] = api_section.get("max_retries", 3)
                conf_data["retry_backoff_sec"] = api_section.get("retry_backoff_sec", 2)
                if isinstance(api_section, dict):
                    localdb = api_section.get("localdb", {})
                    conf_data["localdb_enabled"] = localdb.get("enabled", False)

                    for service in ["crossref", "cinii", "semanticscholar", "jstage", "arxiv"]:
                        detail = api_section.get(service, {})
                        conf_data[f"{service}_base_url"] = detail.get("base_url")
                        conf_data[f"{service}_timeout"] = detail.get("timeout", 10)
                        conf_data[f"{service}_wait_sec"] = detail.get("wait_sec", 0)
                
                conf_data["venue_abbrev_map"] = raw_data.get("venue_abbreviations", {})
        
        return cls(**{k: v for k, v in conf_data.items() if v is not None})

settings = Settings.load_settings()
import os
import yaml
from pathlib import Path
from dotenv import load_dotenv

# .env ファイルの読み込み
load_dotenv()

# config.ymlのパスを計算（core/config.py から見て1つ上のディレクトリ）
BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.yml"
# core/config.py
class Settings:
    def __init__(self):
        # YAMLファイルの読み込み
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            self._config = yaml.safe_load(f)
        
        # --- YAMLからの設定値 ---
        self.similarity_threshold = self._config.get("search", {}).get("similarity_threshold", 0.90)
        self.doi_base_url = self._config.get("api", {}).get("doi_base_url", "https://doi.org/")

        # Crossref
        self.crossref_base_url = self._config.get("api", {}).get("crossref", {}).get("base_url", "https://api.crossref.org/works")
        self.crossref_timeout = self._config.get("api", {}).get("crossref", {}).get("timeout", 10)
        
        # CiNii
        self.cinii_appid = os.getenv("CINII_APPID", "")
        self.cinii_base_url = self._config.get("api", {}).get("cinii", {}).get("base_url", "https://cir.nii.ac.jp/opensearch/v2")
        self.cinii_timeout = self._config.get("api", {}).get("cinii", {}).get("timeout", 10)
        
        # Semantic Scholar
        self.s2_api_key = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
        self.s2_base_url = self._config.get("api", {}).get("semanticscholar", {}).get("base_url", "https://api.semanticscholar.org/graph/v1/paper/search")
        self.s2_timeout = self._config.get("api", {}).get("semanticscholar", {}).get("timeout", 10)

        # J-STAGE
        self.jstage_base_url = self._config.get("api", {}).get("jstage", {}).get("base_url", "https://api.jstage.jst.go.jp/searchapi/do")
        self.jstage_timeout = self._config.get("api", {}).get("jstage", {}).get("timeout", 10)

        # arXiv
        self.arxiv_base_url = self._config.get("api", {}).get("arxiv", {}).get("base_url", "http://export.arxiv.org/api/query")
        self.arxiv_timeout = self._config.get("api", {}).get("arxiv", {}).get("timeout", 10)
        
        # 辞書データ
        self.venue_abbrev_map = self._config.get("venue_abbreviations", {})
        
        # --- 環境変数 (.env) からの設定値 ---
        self.crossref_mailto = os.getenv("CROSSREF_MAILTO", "")
        

# シングルトンとしてインスタンス化（他のファイルはこれをインポートする）
settings = Settings()

from typing import Optional, Tuple
from api_clients.base_client import BaseAPIClient
from core.config import settings
from models import InputData, VerifiedCitationInfo

class LocalDBClient(BaseAPIClient):
    """Client for searching the internal laboratory database."""

    @property
    def api_name(self) -> str:
        return "Lab Local DB"

    @property
    def api_prefix(self) -> str:
        return "localdb"

    def _execute_search(self, input_data: InputData) -> Tuple[Optional[VerifiedCitationInfo], Optional[str]]:
        # TODO: Implement the actual local DB lookup in the future.
        return None, None
        # # example implementation outline:
        # 1. ローカルDB（社内/学内API）への検索リクエスト
        # URL や Timeout は親クラスが自動設定
        # headers = {"Authorization": f"Bearer {settings.localdb_api_key}"} if hasattr(settings, 'localdb_api_key') else {}
        # params = {"title": input_data.parsed_data.title}
        
        # response = self._make_request(params=params, headers=headers)
        
        # # 2. 内部DBに存在しない場合はすぐ諦める（外部APIへフォールバックするため）
        # if not response or response.status_code != 200:
        #     return None, None

        # data = response.json()
        # matches = data.get("matches", [])
        # if not matches:
        #     return None, None

        # best_match = matches[0]

        # # 3. DBに保存されている情報を読み込む
        # metadata = VerifiedCitationInfo(
        #     title=best_match.get("title", ""),
        #     authors=best_match.get("authors", []),
        #     year=best_match.get("year"),
        #     venue=best_match.get("venue", ""),
        #     doi=best_match.get("doi"),
        #     url=best_match.get("url", "")
        # )

        # # 4. 【重要】ローカルDBの最大の利点
        # # すでに研究室のルール（略称など）で整形済みの完璧な BibTeX が
        # # 保存されているはずなので、それをそのまま返す。
        # saved_bibtex = best_match.get("formatted_bibtex")

        # return metadata, saved_bibtex

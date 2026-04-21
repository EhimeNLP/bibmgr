from typing import Optional, Tuple
from api_clients.base_client import BaseAPIClient
from models.input_models import InputData
from models.output_models import Metadata

class LocalDBClient(BaseAPIClient):
    """C担当が構築する研究室内部DB（登録済み文献）を検索するクライアント"""

    @property
    def api_name(self) -> str:
        return "Lab Local DB"

    def search(self, input_data: InputData) -> Tuple[Optional[Metadata], Optional[str]]:
        # TODO: 将来的にC担当が作成したDB検索エンドポイントへリクエストを送る処理を実装
        # 例: response = requests.get("url", params={"title": ...})
        # 現在はダミー
        return None, None
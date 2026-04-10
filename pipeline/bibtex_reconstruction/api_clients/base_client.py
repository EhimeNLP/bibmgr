from abc import ABC, abstractmethod
from typing import Optional, Tuple
from ..models.input_models import InputData
from ..models.output_models import Metadata

class BaseAPIClient(ABC):
    """
    各外部API（Crossref, CiNii, J-STAGE, arXiv）の共通インターフェース
    """
    
    @property
    @abstractmethod
    def api_name(self) -> str:
        """APIの名前（ログ出力用など）"""
        pass

    @abstractmethod
    def search(self, input_data: InputData) -> Tuple[Optional[Metadata], Optional[str]]:
        """
        検索を実行し、共通のMetadata形式と、生のBibTeX文字列を返す
        
        Returns:
            Tuple[Metadata, str]: (統一フォーマットのメタデータ, APIから取得した生のBibTeX)
            見つからなかった場合は (None, None) を返す
        """
        pass
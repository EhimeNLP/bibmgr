from typing import List, Optional
from pydantic import BaseModel, Field

class ParsedData(BaseModel):
    title: Optional[str] = Field(None, description="抽出された論文タイトル")
    authors: Optional[List[str]] = Field(None, description="抽出された著者名のリスト")
    year: Optional[int] = Field(None, description="発行年")
    journal_or_book: Optional[str] = Field(None, description="学会名や雑誌名")

class InputData(BaseModel):
    source_pdf: str = Field(..., description="元のPDFファイル名")
    ref_id: str = Field(..., description="論文内での参照番号 (例: ref_1)")
    parsed_data: ParsedData
    raw_reference_text: str = Field(..., description="画像から読み取った生の文字列")
    citation_contexts: List[str] = Field(default_factory=list, description="引用された文脈")
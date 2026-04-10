from typing import List, Optional
from pydantic import BaseModel, Field

class Metadata(BaseModel):
    title: str
    authors: List[str]
    year: Optional[int] = None
    venue: Optional[str] = None
    doi: Optional[str] = None
    url: Optional[str] = None

class OutputData(BaseModel):
    source_pdf: str
    ref_id: str
    status: str = Field(..., description="'success', 'needs_review', 'not_found' のいずれか")
    confidence_score: Optional[float] = Field(None, description="検索結果の自信度 (0.0~1.0)")
    metadata: Optional[Metadata] = None
    bibtex: Optional[str] = Field(None, description="整形済みのBibTeX文字列")
    citation_contexts: List[str]
    original_input: dict = Field(..., description="人間がレビューする際の比較用生データ")
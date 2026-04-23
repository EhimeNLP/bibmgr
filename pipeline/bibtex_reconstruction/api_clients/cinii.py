import re
from typing import Optional, Tuple
from models.input_models import InputData
from models.output_models import Metadata
from api_clients.base_client import BaseAPIClient
from core.config import settings

def _extract_field(raw_bibtex: str, field_name: str) -> Optional[str]:
    if not raw_bibtex: return None
    pattern = rf"{field_name}\s*=\s*[{{|\"](.*?)[}}|\"]\s*(?:,|$)"
    match = re.search(pattern, raw_bibtex, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else None

class CiNiiClient(BaseAPIClient):
    @property
    def api_name(self) -> str:
        return "CiNii API"

    def search(self, input_data: InputData) -> Tuple[Optional[Metadata], Optional[str]]:
        if not input_data.parsed_data or not input_data.parsed_data.title:
            return None, None
            
        title = input_data.parsed_data.title
        endpoint_url = f"{settings.cinii_base_url}/all"  

        params = {"title": title, "format": "json", "count": 1}
        if settings.cinii_appid:
            params["appid"] = settings.cinii_appid

        response = self._make_request(
            endpoint_url, 
            params=params, 
            timeout=settings.cinii_timeout
        )
        if not response:
            return None, None

        items = response.json().get("items", [])
        if not items:
            return None, None

        best_match = items[0]
                
        title = best_match.get("title", "")
        authors = best_match.get("dc:creator", [])
        year = self._extract_year(best_match.get("prism:publicationDate", ""))
        venue = best_match.get("prism:publicationName", "")
        url = best_match.get("@id", "")
        
        doi = None
        for id_item in best_match.get("dc:identifier", [{}]):
            if id_item.get("@type") == "cir:DOI":
                doi = id_item.get("@value")
                break

        metadata = Metadata(title=title, authors=authors, year=year, venue=venue, doi=doi, url=url)

        # 共通のDOI解決メソッドを利用
        raw_bibtex = self._fetch_bibtex_from_doi(doi, timeout=settings.crossref_timeout)
        
        # 見つからない場合は独自の.bib取得裏技を利用
        if not raw_bibtex:
            crid_url = best_match.get("link", {}).get("@id", "")
            if crid_url:
                bib_resp = self._make_request(f"{crid_url}.bib", timeout=settings.cinii_timeout, max_retries=1)
                if bib_resp:
                    raw_bibtex = bib_resp.text
                    metadata.doi = _extract_field(raw_bibtex, "doi") or metadata.doi

        return metadata, raw_bibtex
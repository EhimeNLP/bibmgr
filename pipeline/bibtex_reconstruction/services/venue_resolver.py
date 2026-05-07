import requests
from typing import Optional
from core.config import settings

class VenueResolver:
    """
    Resolves formal venue names into abbreviations (acronyms) using DBLP API
    and local YAML dictionary.
    """
    _cache = {}

    @classmethod
    def resolve(cls, raw_venue: str) -> str:
        """
        Main entry point to resolve a venue name.
        
        Args:
            raw_venue (str): The raw venue string from an API (e.g., 'Proceedings of ACL').
            
        Returns:
            str: The resolved abbreviation or the original string if not found.
        """
        if not raw_venue:
            return ""

        # 1. Check Memory Cache
        if raw_venue in cls._cache:
            return cls._cache[raw_venue]

        # 2. Check Local YAML Dictionary (High Priority for Domestic Conferences)
        if raw_venue in settings.venue_abbrev_map:
            return settings.venue_abbrev_map[raw_venue]

        # 3. Request DBLP API
        resolved = cls._fetch_from_dblp(raw_venue)
        
        # 4. Fallback: If DBLP fails, return the original (or cleaned) name
        final_name = resolved if resolved else raw_venue
        cls._cache[raw_venue] = final_name
        
        return final_name

    @classmethod
    def _fetch_from_dblp(cls, query: str) -> Optional[str]:
        """Queries DBLP Venue API for acronyms."""
        params = {"q": query, "format": "json", "h": 1}
        try:
            response = requests.get(settings.dblp_venue_api_url, params=params, timeout=5)
            if response.status_code != 200:
                return None
            
            data = response.json()
            hits = data.get("result", {}).get("hits", {}).get("hit", [])
            
            if not hits:
                return None

            info = hits[0].get("info", {})
            acronym = info.get("acronym")
            
            return acronym if acronym else None
            
        except Exception as e:
            print(f"[VenueResolver] DBLP Error: {e}")
            return None
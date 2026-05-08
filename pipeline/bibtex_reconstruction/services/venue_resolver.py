import requests
from typing import Optional
from core.config import settings

class VenueResolver:
    """
    Resolves venue name strings into a (formal_name, abbreviation) pair.

    Given any venue string from an external API — whether it is already an
    abbreviation, a full formal name, or something in between — this class
    returns a consistent tuple so callers always know both forms.

    Return contract of resolve():
        (formal_name, abbreviation)
        - formal_name : the full name (str). Falls back to raw_venue if unknown.
        - abbreviation: the short form (Optional[str]).
                        None when no abbreviation could be determined.

    Resolution order:
        1. Normalize the input (strip + lowercase) for all lookups.
        2. If the input is already a known abbreviation:
               → (formal_name, raw_venue)  using the reverse map from YAML.
        3. Check the in-memory cache.
        4. Check the local YAML map  (keys are lowercase full names).
        5. Query the DBLP Venue API.
        6. Fallback: (raw_venue, None)  — no abbreviation found.
    """

    # Cache keyed by *normalized* venue string → (formal_name, abbrev | None).
    _cache: dict[str, tuple[str, Optional[str]]] = {}

    # Reverse map: abbreviation → formal name (lowercase), built from config.yml.
    # e.g. {"ACL": "association for computational linguistics", ...}
    _abbrev_to_formal: dict[str, str] = {}

    # Set of known abbreviations for O(1) membership test.
    _known_abbrevs: set[str] = set()

    # Lazy-init flag.
    _initialized: bool = False

    # ---------------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------------

    @classmethod
    def resolve(cls, raw_venue: str) -> tuple[str, Optional[str]]:
        """
        Resolve a venue string into a (formal_name, abbreviation) pair.

        Args:
            raw_venue (str): Any venue string from an external API.
                             May be a full name, an abbreviation, or mixed-case.

        Returns:
            tuple[str, Optional[str]]:
                - formal_name (str)          : Full name. Falls back to raw_venue.
                - abbreviation (Optional[str]): Short form, or None if unavailable.

        Examples:
            resolve("Neural Information Processing Systems")
                → ("Neural Information Processing Systems", "NeurIPS")

            resolve("NeurIPS")                # input is already an abbreviation
                → ("neural information processing systems", "NeurIPS")

            resolve("Some Unknown Workshop")  # not in YAML or DBLP
                → ("Some Unknown Workshop", None)
        """
        if not raw_venue:
            return "", None

        cls._ensure_initialized()

        normalized = raw_venue.strip().lower()

        # 1. Input is already a known abbreviation — look up formal name via reverse map.
        if raw_venue in cls._known_abbrevs:
            formal = cls._abbrev_to_formal.get(raw_venue, raw_venue)
            return formal, raw_venue

        # 2. In-memory cache (normalized key).
        if normalized in cls._cache:
            return cls._cache[normalized]

        # 3. Local YAML dictionary (keys stored as lowercase full names).
        if normalized in settings.venue_abbrev_map:
            abbrev = settings.venue_abbrev_map[normalized]
            result: tuple[str, Optional[str]] = (raw_venue, abbrev)
            cls._cache[normalized] = result
            return result

        # 4. DBLP Venue API.
        abbrev = cls._fetch_from_dblp(raw_venue)
        result = (raw_venue, abbrev)  # abbrev is None when DBLP finds nothing
        cls._cache[normalized] = result
        return result

    # ---------------------------------------------------------------------------
    # Private helpers
    # ---------------------------------------------------------------------------

    @classmethod
    def _ensure_initialized(cls) -> None:
        """
        Builds _known_abbrevs and _abbrev_to_formal from settings on first call.
        """
        if not cls._initialized:
            for formal_lower, abbrev in settings.venue_abbrev_map.items():
                cls._known_abbrevs.add(abbrev)
                # If multiple full names map to the same abbrev (e.g. old/new WMT names),
                # the first entry in the YAML wins as the canonical formal name.
                if abbrev not in cls._abbrev_to_formal:
                    cls._abbrev_to_formal[abbrev] = formal_lower
            cls._initialized = True

    @classmethod
    def _fetch_from_dblp(cls, query: str) -> Optional[str]:
        """
        Queries the DBLP Venue API for an acronym matching *query*.

        Args:
            query (str): The venue name to look up.

        Returns:
            Optional[str]: The acronym if found, otherwise None.
        """
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
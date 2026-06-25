from typing import Optional, Tuple
from api_clients.base_client import BaseAPIClient
from models import InputData, VerifiedCitationInfo


class LocalDBClient(BaseAPIClient):
    """
    Client for searching the internal laboratory database.

    This client is intentionally disabled by default (config.yml: api.localdb.enabled: false).
    When enabled, it is called before any external API and its result short-circuits the
    remaining search pipeline (confidence_score = 1.0).

    To activate: set `api.localdb.enabled: true` and `api.localdb.base_url` in config.yml,
    then implement _execute_search() below.
    """

    @property
    def api_name(self) -> str:
        return "Lab Local DB"

    @property
    def api_prefix(self) -> str:
        return "localdb"

    def _execute_search(self, input_data: InputData) -> Tuple[Optional[VerifiedCitationInfo], Optional[str]]:
        # TODO: Implement the actual local DB lookup.
        #
        # Implementation outline:
        #   headers = {"Authorization": f"Bearer {settings.localdb_api_key}"} if hasattr(settings, 'localdb_api_key') else {}
        #   params  = {"title": input_data.parsed_data.title}
        #   response = self._make_request(params=params, headers=headers)
        #
        #   if not response or response.status_code != 200:
        #       return None, None
        #
        #   matches = response.json().get("matches", [])
        #   if not matches:
        #       return None, None
        #
        #   best = matches[0]
        #   metadata = VerifiedCitationInfo(
        #       title=best.get("title", ""),
        #       authors=best.get("authors", []),
        #       year=best.get("year"),
        #       venue=best.get("venue", ""),
        #       doi=best.get("doi"),
        #       url=best.get("url", ""),
        #   )
        #   # The local DB stores already-formatted BibTeX that follows lab rules,
        #   # so return it directly without going through apply_lab_rules().
        #   return metadata, best.get("formatted_bibtex")
        raise NotImplementedError(
            "LocalDBClient._execute_search() is not yet implemented. "
            "Set api.localdb.enabled: false in config.yml to skip this client."
        )
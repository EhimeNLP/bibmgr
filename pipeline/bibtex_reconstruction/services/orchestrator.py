from models.input_models import InputData
from api_clients.local_db import LocalDBClient
from api_clients.crossref import CrossrefClient
from core.utils import calculate_similarity
from core.config import settings

class SearchOrchestrator:
    def __init__(self):
        self.local_client = LocalDBClient()
        self.external_clients = [
            CrossrefClient(),
            # apiの追加はここ
        ]

    def execute_search(self, input_data: InputData) -> dict:
        original_title = input_data.parsed_data.title if input_data.parsed_data else ""
        
        print(f"Searching with {self.local_client.api_name}...")
        local_metadata, local_bibtex = self.local_client.search(input_data)
        
        if local_metadata:
            return {
                "status": "already_exists",
                "confidence_score": 1.0,
                "metadata": local_metadata,
                "bibtex": local_bibtex
            }

        for client in self.external_clients:
            print(f"Searching with {client.api_name}...")
            ext_metadata, ext_bibtex = client.search(input_data)
            
            if ext_metadata:
                score = calculate_similarity(original_title, ext_metadata.title)
                
                status = "success" if score >= settings.similarity_threshold else "needs_review"

                return {
                    "status": status,
                    "confidence_score": score,
                    "metadata": ext_metadata,
                    "bibtex": ext_bibtex
                }

        return {
            "status": "not_found",
            "confidence_score": 0.0,
            "metadata": None,
            "bibtex": None
        }

orchestrator = SearchOrchestrator()
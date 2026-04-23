from models.input_models import InputData
from api_clients.local_db import LocalDBClient
from api_clients.crossref import CrossrefClient
from api_clients.cinii import CiNiiClient
from api_clients.semantic_scholar import SemanticScholarClient
from api_clients.jstage import JStageClient
from api_clients.arxiv import ArxivClient

from core.utils import calculate_similarity
from core.config import settings

class SearchOrchestrator:
    def __init__(self):
        self.local_client = LocalDBClient()
        self.external_clients = [
            CrossrefClient(),
            SemanticScholarClient(),
            CiNiiClient(),
            JStageClient(),
            ArxivClient(),
        ]

    def execute_search(self, input_data: InputData) -> dict:
        original_title = input_data.parsed_data.title if input_data.parsed_data else ""
        
        print(f"Searching with {self.local_client.api_name}...")
        local_metadata, local_bibtex = self.local_client.search(input_data)
        
        if local_metadata:
            print(f"Found in local DB: {local_metadata.title}")
            return {
                "status": "already_exists",
                "confidence_score": 1.0,
                "metadata": local_metadata,
                "bibtex": local_bibtex,
                "source_api": self.local_client.api_name
            }
        
        best_review_result = None
        for client in self.external_clients:
            print(f"----------------------------------------------------------------")
            print(f"Searching with {client.api_name}...")
            ext_metadata, ext_bibtex = client.search(input_data)
            print(f"Result from {client.api_name}: {ext_metadata.title if ext_metadata else 'No metadata found'}")
            if ext_metadata:
                score = calculate_similarity(original_title, ext_metadata.title)
                print(f"Similarity score with {client.api_name}: {score:.4f}")
                # if score >= settings.similarity_threshold:
                #     return {
                #         "status": "success",
                #         "confidence_score": score,
                #         "metadata": ext_metadata,
                #         "bibtex": ext_bibtex,
                #         "source_api": client.api_name
                #     }
                if best_review_result is None or score > best_review_result["confidence_score"]:
                    best_review_result = {
                        "status": "needs_review",
                        "confidence_score": score,
                        "metadata": ext_metadata,
                        "bibtex": ext_bibtex,
                        "source_api": client.api_name
                    }
        
        if best_review_result:
            return best_review_result

        return {
            "status": "not_found",
            "confidence_score": 0.0,
            "metadata": None,
            "bibtex": None
        }

orchestrator = SearchOrchestrator()
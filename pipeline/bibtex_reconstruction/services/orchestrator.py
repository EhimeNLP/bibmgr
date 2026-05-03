import json
import concurrent.futures
from models import InputData, ProcessedReference, CandidateResult
from api_clients import (
    LocalDBClient,
    CrossrefClient,
    CiNiiClient,
    SemanticScholarClient,
    JStageClient,
    ArxivClient,
)

from core import calculate_similarity, settings

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

    def execute_search(self, input_data: InputData) -> ProcessedReference:
        original_title = input_data.parsed_data.title if input_data.parsed_data.title else ""
        ref_id = input_data.parsed_data.id
        candidates = []
        
        # 1. Search in Local DB
        local_metadata, local_bibtex = self.local_client.search(input_data)
        if local_metadata:
            return ProcessedReference(
                ref_id=ref_id,
                overall_status="success",
                original_data=input_data.parsed_data,
                candidates=[CandidateResult(
                    source_api=self.local_client.api_name,
                    status="success",
                    confidence_score=1.0,
                    verified_info=local_metadata,
                    bibtex=local_bibtex
                )]
            )
        
        # 2. Search across ALL external APIs
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.external_clients)) as executor:
            future_to_client = {
                executor.submit(client.search, input_data): client 
                for client in self.external_clients
            }

            for future in concurrent.futures.as_completed(future_to_client):
                client = future_to_client[future]
                try:
                    ext_metadata, ext_bibtex = future.result()
                    if ext_metadata:
                        score = calculate_similarity(original_title, ext_metadata.title)
                        api_status = "success" if score >= settings.similarity_threshold else "needs_review"
                        candidates.append(CandidateResult(
                            source_api=client.api_name,
                            status=api_status,
                            confidence_score=score,
                            verified_info=ext_metadata,
                            bibtex=ext_bibtex
                        ))
                    else:
                        candidates.append(CandidateResult(
                            source_api=client.api_name, status="not_found", confidence_score=0.0
                        ))
                except Exception as e:
                    print(f"Error from {client.api_name}: {e}")
                    candidates.append(CandidateResult(
                        source_api=client.api_name, status="not_found", confidence_score=0.0
                    ))

        # 3. Determine overall status for the reference
        # We only consider APIs that actually found something to determine the best score
        found_candidates = [c for c in candidates if c.status != "not_found"]
        found_candidates.sort(key=lambda x: x.confidence_score, reverse=True)
        overall_status = found_candidates[0].status if found_candidates else "not_found"

        return ProcessedReference(
            ref_id=ref_id,
            overall_status=overall_status,
            original_data=input_data.parsed_data,
            candidates=found_candidates + [c for c in candidates if c.status == "not_found"]
        )


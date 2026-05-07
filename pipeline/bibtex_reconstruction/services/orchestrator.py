import concurrent.futures
from typing import List
from models import InputData, ProcessedReference, CandidateResult
from api_clients import (
    LocalDBClient, CrossrefClient, CiNiiClient, 
    SemanticScholarClient, JStageClient, ArxivClient,
)
from core import calculate_similarity, settings
from core.constants import ProcessingStatus
from services.formatter import apply_lab_rules

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

    def reconstruct_reference(self, input_data: InputData) -> ProcessedReference:
        result = self.execute_search(input_data)
        return self._format_candidates_parallel(result, input_data.parsed_data.raw_text)

    def execute_search(self, input_data: InputData) -> ProcessedReference:
        original_title = input_data.parsed_data.title or ""
        ref_id = input_data.parsed_data.id
        candidates = []
        
        # Local DB check
        local_metadata, local_bibtex = self.local_client.search(input_data)
        if local_metadata:
            return ProcessedReference(
                ref_id=ref_id,
                overall_status=ProcessingStatus.SUCCESS,
                original_data=input_data.parsed_data,
                candidates=[CandidateResult(
                    source_api=self.local_client.api_name,
                    status=ProcessingStatus.SUCCESS,
                    confidence_score=1.0,
                    verified_info=local_metadata,
                    bibtex=local_bibtex
                )]
            )
        
        # External APIs (Parallel)
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
                        status = ProcessingStatus.SUCCESS if score >= settings.similarity_threshold else ProcessingStatus.NEEDS_REVIEW
                        candidates.append(CandidateResult(
                            source_api=client.api_name, status=status,
                            confidence_score=score, verified_info=ext_metadata, bibtex=ext_bibtex
                        ))
                    else:
                        candidates.append(CandidateResult(source_api=client.api_name, status=ProcessingStatus.NOT_FOUND))
                except Exception as e:
                    print(f"[Search Error] {client.api_name}: {e}")
                    candidates.append(CandidateResult(source_api=client.api_name, status=ProcessingStatus.API_ERROR))

        return ProcessedReference(
            ref_id=ref_id,
            overall_status=ProcessingStatus.determine_overall([c.status for c in candidates]),
            original_data=input_data.parsed_data,
            candidates=sorted(candidates, key=lambda x: x.confidence_score, reverse=True)
        )

    def _format_candidates_parallel(self, result: ProcessedReference, raw_text: str) -> ProcessedReference:
        targets = [c for c in result.candidates if c.verified_info and c.status != ProcessingStatus.NOT_FOUND]
        if not targets:
            return result

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            future_to_cand = {
                executor.submit(apply_lab_rules, c.bibtex, c.verified_info, raw_text): c 
                for c in targets
            }
            for future in concurrent.futures.as_completed(future_to_cand):
                cand = future_to_cand[future]
                try:
                    formatted_bib = future.result()
                    cand.bibtex = formatted_bib
                    
                    if formatted_bib and "unknown" in formatted_bib.split('\n')[0].lower():
                        if cand.status == ProcessingStatus.SUCCESS:
                            cand.status = ProcessingStatus.NEEDS_REVIEW
                except Exception as e:
                    print(f"[Formatter Error] {cand.source_api}: {e}")
                    cand.status = ProcessingStatus.API_ERROR

        result.overall_status = ProcessingStatus.determine_overall([c.status for c in result.candidates])
        return result
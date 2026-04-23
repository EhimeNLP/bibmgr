from fastapi import FastAPI, HTTPException
from models.input_models import InputData
from models.output_models import OutputData
from services.orchestrator import orchestrator
from services import formatter

app = FastAPI(title="BibTeX-Reconstruction-API")

@app.post("/reconstruct", response_model=OutputData)
async def reconstruct_bibtex(request_data: InputData):
    try:
        search_result = orchestrator.execute_search(request_data)
        
        raw_bibtex = search_result.get("bibtex")
        metadata = search_result.get("metadata")
        current_status = search_result.get("status")

        formatted_bibtex, final_status = formatter.apply_lab_rules(
            raw_bibtex, 
            metadata, 
            current_status
        )

        original_input_dict = {
            "raw_reference_text": request_data.raw_reference_text,
            "parsed_data": request_data.parsed_data.model_dump() if request_data.parsed_data else None
        }

        return OutputData(
            source_pdf=request_data.source_pdf,
            ref_id=request_data.ref_id,
            status=final_status, # already_exists, success, needs_review, not_found
            confidence_score=search_result["confidence_score"],
            metadata=search_result["metadata"],
            bibtex=formatted_bibtex,
            citation_contexts=request_data.citation_contexts,
            original_input=original_input_dict,
            source_api=search_result.get("source_api")
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline Error: {str(e)}")
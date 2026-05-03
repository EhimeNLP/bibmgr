import json
import concurrent.futures
from fastapi import FastAPI, HTTPException
from models import DocumentRoot, InputData, OutputData, ProcessedReference
from services.orchestrator import SearchOrchestrator
from services.formatter import apply_lab_rules

app = FastAPI(title="BibTeX-Reconstruction-API")
orchestrator = SearchOrchestrator()

def format_candidates_parallel(result: ProcessedReference, raw_text: str):
    target_candidates = [
        c for c in result.candidates 
        if c.status != "not_found" and c.verified_info
    ]

    if not target_candidates:
        return result

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_cand = {
            executor.submit(
                apply_lab_rules, 
                cand.bibtex, 
                cand.verified_info, 
                raw_text, 
                cand.status
            ): cand for cand in target_candidates
        }

        for future in concurrent.futures.as_completed(future_to_cand):
            cand = future_to_cand[future]
            try:
                formatted_bib, final_status = future.result()
                cand.bibtex = formatted_bib
                cand.status = final_status
            except Exception as e:
                print(f"Formatter error for {cand.source_api}: {e}")
                cand.status = "needs_review"

    success_cands = [c for c in result.candidates if c.status == "success"]
    result.overall_status = "success" if success_cands else "needs_review"
    
    return result

# --- API エンドポイント ---
@app.post("/reconstruct", response_model=OutputData)
async def reconstruct_bibtex(request_data: DocumentRoot):
    try:
        processed_refs = []
        for ref_data in request_data.references:
            # 1. 検索 (Orchestrator: 生データ取得)
            task_envelope = InputData(parsed_data=ref_data)
            search_result = orchestrator.execute_search(task_envelope)
            
            # 2. 並列整形 (Formatter: 研究室ルール適用)
            final_result = format_candidates_parallel(search_result, ref_data.raw_text)
            processed_refs.append(final_result)
            
        return OutputData(
            title=request_data.title,
            authors=request_data.authors,
            year=request_data.year,
            doi=request_data.doi,
            abstract=request_data.abstract,
            reference_count=len(processed_refs),
            processed_references=processed_refs,
            saved_files=request_data.saved_files
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline Error: {str(e)}")

# --- ローカル実行用 CLI ---
def run_local(input_path: str, output_path: str):
    print(f"Reading input from: {input_path}")
    with open(input_path, 'r', encoding='utf-8') as f:
        raw_json = json.load(f)
    
    document = DocumentRoot.model_validate(raw_json)
    
    processed_refs = []
    for ref_data in document.references:
        print(f"Processing: {ref_data.id}")
        search_result = orchestrator.execute_search(InputData(parsed_data=ref_data))
        final_result = format_candidates_parallel(search_result, ref_data.raw_text)
        processed_refs.append(final_result)

    final_output = OutputData(
        title=document.title,
        authors=document.authors,
        year=document.year,
        doi=document.doi,
        abstract=document.abstract,
        processed_references=processed_refs,
        reference_count=len(processed_refs),
        saved_files=document.saved_files
    )

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(final_output.model_dump(exclude_none=True), f, ensure_ascii=False, indent=2)
    print(f"Saved results to: {output_path}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=str, help="Path to input JSON")
    parser.add_argument("--output", type=str, default="output.json", help="Path to output JSON")
    args = parser.parse_args()

    if args.input:
        run_local(args.input, args.output)
    else:
        import uvicorn
        uvicorn.run(app, host="0.0.0.0", port=8000)
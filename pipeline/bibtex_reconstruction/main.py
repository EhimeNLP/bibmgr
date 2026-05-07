import json
from fastapi import FastAPI, HTTPException
from models import DocumentRoot, InputData, OutputData
from services.orchestrator import SearchOrchestrator

app = FastAPI(title="BibTeX-Reconstruction-API")
orchestrator = SearchOrchestrator()

@app.post("/reconstruct", response_model=OutputData)
async def reconstruct_bibtex(request_data: DocumentRoot):
    try:
        processed_refs = [
            orchestrator.reconstruct_reference(InputData(parsed_data=ref))
            for ref in request_data.references
        ]
        return OutputData(
            **request_data.model_dump(exclude={"references", "reference_count"}),
            reference_count=len(processed_refs),
            processed_references=processed_refs
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline Error: {str(e)}")

def run_local(input_path: str, output_path: str):
    with open(input_path, 'r', encoding='utf-8') as f:
        document = DocumentRoot.model_validate(json.load(f))
    
    processed_refs = []
    for ref in document.references:
        print(f"Processing: {ref.id} - {ref.title[:30]}...")
        processed_refs.append(orchestrator.reconstruct_reference(InputData(parsed_data=ref)))

    output = OutputData(
        **document.model_dump(exclude={"references", "reference_count"}),
        reference_count=len(processed_refs),
        processed_references=processed_refs
    )

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output.model_dump(exclude_none=True), f, ensure_ascii=False, indent=2)
    print(f"Done! Results saved to {output_path}")

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Run BibTeX Reconstruction Pipeline")
    parser.add_argument("--input", type=str, help="Path to input JSON file")
    parser.add_argument("--output", type=str, default="output.json", help="Path to output JSON file")
    args = parser.parse_args()

    if args.input:
        run_local(args.input, args.output)
    else:
        import uvicorn
        uvicorn.run(app, host="localhost", port=8000)


if __name__ == "__main__":
    main()
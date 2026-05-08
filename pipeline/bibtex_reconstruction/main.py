import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from fastapi import FastAPI, HTTPException
from models import DocumentRoot, InputData, OutputData
from services.orchestrator import SearchOrchestrator
from core.config import settings

app = FastAPI(title="BibTeX-Reconstruction-API")
orchestrator = SearchOrchestrator()

# Shared thread pool for offloading synchronous orchestrator work.
# max_workers mirrors max_parallel_requests so the pool scales with config.
_executor = ThreadPoolExecutor(max_workers=settings.max_parallel_requests)


@app.post("/reconstruct", response_model=OutputData)
async def reconstruct_bibtex(request_data: DocumentRoot):
    """
    Reconstruct BibTeX entries for all references in the document.

    Each reference is processed by SearchOrchestrator.reconstruct_reference(),
    which is a synchronous function that internally uses a ThreadPoolExecutor
    for parallel API calls.  To avoid blocking FastAPI's async event loop,
    every reference is offloaded to a shared thread-pool executor and all
    references are awaited concurrently via asyncio.gather().
    """
    try:
        loop = asyncio.get_event_loop()

        tasks = [
            loop.run_in_executor(
                _executor,
                orchestrator.reconstruct_reference,
                InputData(parsed_data=ref),
            )
            for ref in request_data.references
        ]
        processed_refs = await asyncio.gather(*tasks)

        return OutputData(
            **request_data.model_dump(exclude={"references", "reference_count"}),
            reference_count=len(processed_refs),
            processed_references=list(processed_refs),
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
        processed_references=processed_refs,
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
import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import APIKeyHeader
from models import DocumentRoot, InputData, OutputData
from services.orchestrator import SearchOrchestrator
from core.config import settings

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_api_key(
    x_api_key: str | None = Depends(_API_KEY_HEADER),
) -> None:
    """
    Verify the X-API-Key header.

    - If API_KEY is not set, skip authentication (for development environment).
      Output a WARNING and indicate the open state at startup.
    - If the header is missing or the value does not match, return HTTP 401.
    """
    if not settings.api_key:
        return
    if x_api_key is None or x_api_key != settings.api_key:
        raise HTTPException(
            status_code=401,
            detail="Invalid or missing API key.",
            headers={"WWW-Authenticate": "ApiKey"},
        )


orchestrator = SearchOrchestrator()
_executor: ThreadPoolExecutor | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Resource management when launching and closing the app."""
    global _executor
    if not settings.api_key:
        print(
            "[WARNING] API_KEY is not set. "
            "The /reconstruct endpoint is open to all requests."
        )
    _executor = ThreadPoolExecutor(max_workers=settings.max_parallel_requests)
    yield
    _executor.shutdown(wait=True)


app = FastAPI(title="BibTeX-Reconstruction-API", lifespan=lifespan)

@app.post("/reconstruct", response_model=OutputData, dependencies=[Depends(verify_api_key)])
async def reconstruct_bibtex(request_data: DocumentRoot):
    """
    Reconstruct BibTeX entries for all references in the document.

    Each reference is processed by SearchOrchestrator.reconstruct_reference(),
    which is a synchronous function that internally uses a ThreadPoolExecutor
    for parallel API calls.  To avoid blocking FastAPI's async event loop,
    every reference is offloaded to a shared thread-pool executor and all
    references are awaited concurrently via asyncio.gather().

    Requires a valid ``X-API-Key`` header (configured via ``API_KEY`` in ``.env``).
    Authentication is disabled when ``API_KEY`` is not set (development mode).
    """
    try:
        loop = asyncio.get_running_loop()

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
    with open(input_path, "r", encoding="utf-8") as f:
        document = DocumentRoot.model_validate(json.load(f))

    processed_refs = []
    for ref in document.references:
        print(f"Processing: {ref.id} - {ref.title[:30]}...")
        processed_refs.append(
            orchestrator.reconstruct_reference(InputData(parsed_data=ref))
        )

    output = OutputData(
        **document.model_dump(exclude={"references", "reference_count"}),
        reference_count=len(processed_refs),
        processed_references=processed_refs,
    )

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output.model_dump(exclude_none=True), f, ensure_ascii=False, indent=2)
    print(f"Done! Results saved to {output_path}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Run BibTeX Reconstruction Pipeline")
    parser.add_argument("--input", type=str, help="Path to input JSON file")
    parser.add_argument(
        "--output", type=str, default="output.json", help="Path to output JSON file"
    )
    args = parser.parse_args()

    if args.input:
        run_local(args.input, args.output)
    else:
        import uvicorn
        uvicorn.run(app, host="localhost", port=8000)


if __name__ == "__main__":
    main()
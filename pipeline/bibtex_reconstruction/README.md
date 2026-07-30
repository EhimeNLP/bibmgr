**BibTeX Reconstruction**

This small pipeline compares reference strings extracted from images or PDFs against external APIs and reconstructs normalized BibTeX. It is available through an endpoint exposed by FastAPI.

**Requirements**
- **Python**: 3.12 or later (`.python-version` specifies 3.12)
- Dependencies are declared in `pyproject.toml` and `uv.lock`.

**Project Structure**
- `main.py`: FastAPI application (`POST /reconstruct`).
- `config.yml`: Pipeline settings such as similarity thresholds, API endpoints, and the venue-name dictionary.
- `api_clients/`: Crossref, CiNii, Semantic Scholar, J-Stage, arXiv, and local database clients.
- `core/`: Configuration loading and utility functions.
- `models/`: Pydantic models for `InputData` and `OutputData`.
- `services/`: Search orchestrator (`orchestrator.py`) and BibTeX formatting logic (`formatter.py`).
- `test_data/`: Sample responses and test JSON.

**Local Setup**

```bash
uv sync
```

Set environment variables such as API keys and email addresses in `.env`, for example `CINII_APPID`, `SEMANTIC_SCHOLAR_API_KEY`, and `CROSSREF_MAILTO`.

**Running the Service**

Start the FastAPI server in development mode with:

```bash
uv run uvicorn main:app --reload
```

After startup, the OpenAPI documentation is available at `http://localhost:8000/docs`.

**API (POST /reconstruct)**

The input model is `models.InputData`. A minimal example follows:

```json
{
  "source_pdf": "title.pdf",
  "ref_id": "ref-number",
  "raw_reference_text": "name. title. xx.",
  "parsed_data": {
    "title": "title",
    "authors": ["name"],
    "year": 1111,
    "venue": "venue"
  },
  "citation_contexts": ["According to name..."]
}
```

The endpoint returns `models.OutputData`. Its `status` is one of `success`, `needs_review`, or `not_found`.

**Configuration**

- Similarity thresholds and external API endpoints are managed in `config.yml`.
- Specify API keys and related secrets in `.env`; `core.config` loads these values.

**Test Data**

- `test_data/` contains sample JSON for verification and isolated debugging.

**Development Notes**

- Search flow: `services.orchestrator` checks the local database first. If no match is found, it queries the external clients in sequence and returns the result with the highest similarity as `needs_review`.
- Formatting rules: `services.formatter.apply_lab_rules` extracts and completes BibTeX fields and generates citation keys.

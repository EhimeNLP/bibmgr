# Initialization Pipelines

`pipeline/` contains optional, out-of-band tools for creating an initial bibliography from source PDFs. These tools are intentionally outside the BibMgR application dependency graph and never register records in the shared library automatically. All commands below run from the repository root.

## Stages

| Stage | Input | Primary output | Side effects |
| --- | --- | --- | --- |
| [Metadata extraction](metadata_extraction/README.md) | One or more PDF files | One reviewable extraction JSON document per PDF | May populate model caches; never writes to BibMgR |
| [BibTeX reconstruction](bibtex_reconstruction/README.md) | One extraction JSON document | Validated BibTeX, audit report, and evidence directory | Queries providers and writes configured caches/artifacts; never writes to BibMgR |

The extraction batch array is a run-level result. Reconstruction accepts one document at a time, so use the per-PDF normalized files written below the extraction `--save-dir`.

## End-to-End Usage

Create a working directory and install both locked environments:

```bash
mkdir -p work
uv sync --project pipeline/metadata_extraction --frozen \
  --group gpu --group dev
uv sync --project pipeline/bibtex_reconstruction --frozen
```

Extract one or more PDFs in parallel:

```bash
uv run --project pipeline/metadata_extraction --frozen --group gpu \
  bibmgr-paper-extract papers/*.pdf \
  --paddleocr-vl-device gpu \
  --save-dir work/extracted \
  --jobs 2 \
  > work/extraction-results.json
```

Review a per-PDF normalized document, then reconstruct it:

```bash
uv run --project pipeline/metadata_extraction --frozen \
  bibmgr-paper-parse \
  work/extracted/paper/paper.paper_extraction.json \
  --format markdown \
  --output work/paper-extraction.md

uv run --project pipeline/bibtex_reconstruction --frozen \
  bibtex-reconstruction \
  work/extracted/paper/paper.paper_extraction.json \
  --output work/paper-reconstructed.bib \
  --report-output work/paper-reconstruction-report.json \
  --fail-on-review
```

The example assumes an input named `paper.pdf`. Repeat reconstruction for each per-PDF extraction document selected after review.

## Contracts and Boundaries

- Each stage has its own `pyproject.toml`, `uv.lock`, virtual environment, CLI, tests, and runtime dependencies.
- Stage interfaces are files rather than imports across project boundaries.
- Extraction records OCR/VLM evidence and deterministic heuristic recovery; reconstruction resolves cited works against bibliographic evidence.
- Reconstruction may query external services and use configured LLMs only for search-query improvement and citation-key concept generation.
- Neither stage mutates source PDFs, registers references, or bypasses the shared Rust validation used for emitted BibTeX.

## Documentation

- [Metadata extraction setup, contracts, concurrency, and policy](metadata_extraction/README.md)
- [BibTeX reconstruction setup, contracts, concurrency, and policy](bibtex_reconstruction/README.md)

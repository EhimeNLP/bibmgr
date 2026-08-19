# Metadata Extraction

This stage extracts paper metadata and bibliography references from one or more PDFs with PaddleOCR-VL. It writes reviewable JSON artifacts and never registers records in BibMgR. See the [initialization pipeline overview](../README.md) for the boundary between this stage and BibTeX reconstruction. All commands below run from the repository root.

## Setup

The default environment contains the package and its test dependencies. It can parse an existing PaddleOCR-VL artifact or call an external runner, but it does not include a local Paddle inference runtime:

```bash
uv sync --project pipeline/metadata_extraction --frozen
```

Install the locked GPU runtime without test dependencies:

```bash
uv sync --project pipeline/metadata_extraction --frozen \
  --no-default-groups --group gpu
```

Install the GPU runtime with development and test dependencies:

```bash
uv sync --project pipeline/metadata_extraction --frozen \
  --group gpu --group dev
```

PaddlePaddle wheels are large. On a slow or congested network, increase uv's HTTP limits while retaining the locked dependency graph:

```bash
UV_HTTP_CONNECT_TIMEOUT=30 \
UV_HTTP_TIMEOUT=300 \
UV_HTTP_RETRIES=10 \
uv sync --project pipeline/metadata_extraction --frozen \
  --group gpu --group dev
```

## Configuration

| Mode | Runtime requirement | Primary option |
| --- | --- | --- |
| Local GPU inference | `gpu` dependency group and a visible CUDA device | `--paddleocr-vl-device gpu` |
| Local CPU inference | Separate environment with CPU PaddlePaddle and the `paddleocr-vl` extra | `--paddleocr-vl-device cpu` |
| Existing artifact | Default environment | `--paddleocr-vl-json PATH` |
| External runner | Default environment and an executable runner | `--paddleocr-vl-command COMMAND` or `PADDLEOCR_VL_COMMAND` |
| VLM inference service | PaddleOCR-VL runtime plus a reachable service | `--vl-rec-backend`, `--vl-rec-server-url`, and `--vl-rec-api-model-name` |

Do not install CPU and GPU PaddlePaddle distributions in the same environment. Confirm GPU visibility before local GPU inference:

```bash
nvidia-smi
uv run --project pipeline/metadata_extraction --frozen --group gpu \
  python -c "import paddle; print(paddle.is_compiled_with_cuda()); print(paddle.device.cuda.device_count())"
```

### External Runner Contract

Each worker invokes an external runner independently as:

```text
<command> <pdf-path> --output <json-path>
```

The runner must write JSON with document metadata and references:

```json
{
  "metadata": {
    "title": "Paper title",
    "authors": ["Jane Doe"],
    "abstract": "...",
    "doi": "10.0000/example",
    "year": 2025
  },
  "references": [
    {
      "id": "ref-1",
      "title": "Reference title",
      "authors": ["A. Author"],
      "year": 2020,
      "doi": "10.0000/ref",
      "raw_text": "Raw reference string"
    }
  ]
}
```

## Usage

### One PDF

Run local GPU inference and write one normalized JSON document:

```bash
uv run --project pipeline/metadata_extraction --frozen --group gpu \
  bibmgr-paper-extract paper.pdf \
  --paddleocr-vl-device gpu \
  --output extracted/paper.json
```

Save normalized JSON plus PaddleOCR-VL native JSON and Markdown artifacts:

```bash
uv run --project pipeline/metadata_extraction --frozen --group gpu \
  bibmgr-paper-extract paper.pdf \
  --paddleocr-vl-device gpu \
  --save-dir extracted/paper \
  --summary
```

Normalize an existing PaddleOCR-VL artifact without installing the inference runtime:

```bash
uv run --project pipeline/metadata_extraction --frozen \
  bibmgr-paper-extract paper.pdf \
  --paddleocr-vl-json paddle-result.json \
  --output extracted/paper.json
```

Use a VLM inference service:

```bash
uv run --project pipeline/metadata_extraction --frozen --group gpu \
  bibmgr-paper-extract paper.pdf \
  --paddleocr-vl-device gpu \
  --vl-rec-backend vllm-server \
  --vl-rec-server-url http://localhost:8118/v1 \
  --vl-rec-api-model-name PaddlePaddle/PaddleOCR-VL-1.5
```

### Multiple PDFs

Process multiple PDFs concurrently and retain a run-level JSON result:

```bash
uv run --project pipeline/metadata_extraction --frozen --group gpu \
  bibmgr-paper-extract papers/*.pdf \
  --paddleocr-vl-device gpu \
  --save-dir extracted \
  --jobs 4 \
  --summary \
  > extraction-results.json
```

### Parse Normalized Output

Render one normalized extraction document as compact JSON, Markdown, or CSV:

```bash
uv run --project pipeline/metadata_extraction --frozen \
  bibmgr-paper-parse extracted/paper.json --format json
uv run --project pipeline/metadata_extraction --frozen \
  bibmgr-paper-parse extracted/paper.json --format markdown -o extracted/summary.md
uv run --project pipeline/metadata_extraction --frozen \
  bibmgr-paper-parse extracted/paper.json --format csv -o extracted/references.csv
```

## Input Contract

`bibmgr-paper-extract` accepts existing PDF files as positional arguments. `--paddleocr-vl-json` supplies one document-specific artifact and therefore accepts only one PDF. Batch inputs may come from different directories, but their file stems must be unique when `--save-dir` is used.

`bibmgr-paper-parse` accepts one raw `ExtractionResult.to_dict()` JSON document. A batch array is a run-level result and must be split into per-document files before parsing or reconstruction.

## Output Contract

A successful single-PDF extraction emits one JSON object; a successful batch emits an array in input order. Each document contains `input_pdf`, `engine`, `metadata`, `references`, `warnings`, and `saved_files`. Metadata and reference objects retain normalized fields plus raw evidence.

`--output` names one normalized JSON file and is valid only for one PDF. In a batch, `--save-dir extracted` isolates artifacts under `extracted/<pdf-stem>/`; for example, `paper.pdf` produces `extracted/paper/paper.paper_extraction.json` alongside native artifacts.

If any batch item fails, all submitted work is allowed to finish. The command reports every failed PDF to stderr, emits no stdout JSON, and exits with status 2. Artifacts already written by successful workers remain available for inspection.

The parser retains the source title, authors, year, DOI, abstract, reference count, and each reference's title, authors, year, DOI, venue, and raw text. `bibtex-reconstruction` consumes one raw or parsed document at a time.

## Concurrency and Resource Limits

`--jobs` controls the number of PDFs in flight and defaults to 2. Use `--jobs 1` for sequential execution. Results remain in input order even when workers finish out of order.

Each local worker initializes an independent PaddleOCR-VL runtime, and each external-runner worker starts an independent command. Reduce `--jobs` when model instances exceed available CPU, GPU, or memory capacity, or when a remote inference service imposes a lower concurrency limit.

## Processing Policy

- PaddleOCR-VL layout output is normalized into a stable document and reference shape.
- Missing structured metadata or references may be recovered from extracted text by deterministic heuristics.
- Raw engine evidence remains attached to normalized fields for later review.
- This stage does not resolve references against external bibliographic providers, generate BibTeX, or write to the BibMgR database.

## Programmatic API

`extract_paper(path, config=...)` processes one PDF. `extract_papers(paths, config=..., jobs=2)` processes a batch concurrently and returns `ExtractionResult` values in the same order as `paths`. Batch save-directory isolation, duplicate-stem validation, and aggregated failures match the CLI behavior.

## Testing

```bash
uv run --project pipeline/metadata_extraction --frozen \
  pytest -q pipeline/metadata_extraction/tests
```

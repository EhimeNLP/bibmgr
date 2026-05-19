# PaddleOCR-VL Paper Extraction

This package extracts paper metadata and bibliography references from an input
PDF.

## Sync

CPU/minimal development dependencies are the default:

```bash
uv sync
```

GPU dependencies are explicit:

```bash
uv sync --no-default-groups --group gpu
```

GPU plus development/test dependencies:

```bash
uv sync --group gpu --group dev
```

If syncing GPU dependencies times out while fetching PaddlePaddle wheels, increase uv's HTTP timeout and retry settings:

```bash
UV_HTTP_CONNECT_TIMEOUT=30 \
UV_HTTP_TIMEOUT=300 \
UV_HTTP_RETRIES=10 \
uv sync --no-default-groups --group gpu
```

For GPU plus development/test dependencies:

```bash
UV_HTTP_CONNECT_TIMEOUT=30 \
UV_HTTP_TIMEOUT=300 \
UV_HTTP_RETRIES=10 \
uv sync --group gpu --group dev
```

PaddlePaddle wheels are large and are fetched from PaddlePaddle-hosted package indexes, so the default uv timeout may be too short on slow or congested networks.

## Extract

Run PaddleOCR-VL directly:

```bash
uv run python -m paper_extractor paper.pdf --paddleocr-vl-device gpu --pretty
```

Write normalized JSON:

```bash
uv run python -m paper_extractor paper.pdf \
  --paddleocr-vl-device gpu \
  --output extracted/paper.json
```

Save normalized JSON plus PaddleOCR-VL native JSON/Markdown artifacts:

```bash
uv run python -m paper_extractor paper.pdf \
  --paddleocr-vl-device gpu \
  --save-dir extracted/paper \
  --summary
```

Use an existing PaddleOCR-VL artifact:

```bash
uv run python -m paper_extractor paper.pdf \
  --paddleocr-vl-json paddle-result.json \
  --output extracted/paper.json
```

Use a VLM inference service:

```bash
uv run python -m paper_extractor paper.pdf \
  --paddleocr-vl-device gpu \
  --vl-rec-backend vllm-server \
  --vl-rec-server-url http://localhost:8118/v1 \
  --vl-rec-api-model-name PaddlePaddle/PaddleOCR-VL-1.5
```

GPU runs require a visible CUDA device:

```bash
nvidia-smi
uv run python -c "import paddle; print(paddle.is_compiled_with_cuda()); print(paddle.device.cuda.device_count())"
```

## Parse Output

Extract essential fields from normalized JSON:

```bash
uv run python -m paper_extractor.parse_output extracted/paper.json --format json
uv run bibmgr-paper-parse extracted/paper.json --format markdown -o extracted/summary.md
uv run bibmgr-paper-parse extracted/paper.json --format csv -o extracted/references.csv
```

The parser keeps:

- title
- authors
- year
- DOI
- abstract
- reference count
- reference title/authors/year/DOI/venue/raw text

## Runner Contract

If `--paddleocr-vl-command` or `PADDLEOCR_VL_COMMAND` is used, the runner must
accept:

```bash
<command> <pdf-path> --output <json-path>
```

and write JSON shaped like:

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

## Tests

```bash
uv run python -m unittest discover -s tests -v
```

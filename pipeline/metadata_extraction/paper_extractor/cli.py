from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .extractors import ExtractionConfig, ExtractionError, extract_paper
from .summary import summarize_extraction


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bibmgr-paper-extract",
        description="Extract paper metadata and references with PaddleOCR-VL.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  bibmgr-paper-extract paper.pdf --paddleocr-vl-device gpu --output paper.json\n"
            "  bibmgr-paper-extract paper.pdf --save-dir extracted --pretty\n"
            "  bibmgr-paper-parse extracted/paper.paper_extraction.json --format markdown"
        ),
    )
    parser.add_argument("pdf", type=Path, help="Input PDF path.")
    parser.add_argument(
        "--paddleocr-vl-json",
        type=Path,
        help="Use an existing normalized PaddleOCR-VL JSON artifact instead of running inference.",
    )
    parser.add_argument(
        "--paddleocr-vl-command",
        help="Command for a PaddleOCR-VL runner, or set PADDLEOCR_VL_COMMAND.",
    )
    parser.add_argument("--paddleocr-vl-device", help="PaddleOCR-VL device, e.g. gpu, cpu, xpu, dcu.")
    parser.add_argument("--paddleocr-vl-engine", help="PaddleOCR-VL engine, e.g. paddlepaddle or transformers.")
    parser.add_argument("--vl-rec-backend", help="VLM service backend, e.g. vllm-server, sglang-server.")
    parser.add_argument("--vl-rec-server-url", help="VLM service URL, e.g. http://localhost:8118/v1.")
    parser.add_argument("--vl-rec-api-model-name", help="Model name used by the VLM service.")
    parser.add_argument("--vl-rec-api-key", help="API key used by the VLM service.")
    parser.add_argument("-o", "--output", type=Path, help="Write normalized JSON output to this path.")
    parser.add_argument(
        "--save-dir",
        type=Path,
        help="Save normalized JSON and PaddleOCR-VL native artifacts into this external directory.",
    )
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    parser.add_argument("--summary", action="store_true", help="Print a compact human-readable summary to stderr.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = ExtractionConfig(
        paddleocr_vl_json=args.paddleocr_vl_json,
        paddleocr_vl_command=args.paddleocr_vl_command,
        paddleocr_vl_device=args.paddleocr_vl_device,
        paddleocr_vl_engine=args.paddleocr_vl_engine,
        paddleocr_vl_rec_backend=args.vl_rec_backend,
        paddleocr_vl_rec_server_url=args.vl_rec_server_url,
        paddleocr_vl_rec_api_model_name=args.vl_rec_api_model_name,
        paddleocr_vl_rec_api_key=args.vl_rec_api_key,
        save_dir=args.save_dir,
    )
    try:
        result = extract_paper(args.pdf, config=config)
    except ExtractionError as exc:
        parser.exit(2, f"error: {exc}\n")

    payload = json.dumps(result.to_dict(), ensure_ascii=False, indent=2 if args.pretty else None)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload + "\n", encoding="utf-8")
    else:
        sys.stdout.write(payload + "\n")

    if args.summary:
        sys.stderr.write(summarize_extraction(result.to_dict(), fmt="text") + "\n")
    if args.save_dir:
        sys.stderr.write(f"saved files: {args.save_dir}\n")
    return 0

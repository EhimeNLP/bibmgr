"""Standalone command-line entry point for bibliography initialization."""

from __future__ import annotations

import argparse
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from core.config import settings
from core.constants import ReconstructionOutcome
from models import InputData, ProcessedReference
from services.orchestrator import ReconstructionOrchestrator
from services.source_loader import load_bibliography_fragments


logger = logging.getLogger(__name__)


def reconstruct_file(
    input_path: Path,
    output_path: Path,
    review_path: Path,
    *,
    orchestrator: ReconstructionOrchestrator | None = None,
) -> tuple[list[str], list[ProcessedReference]]:
    """Reconstruct all fragments and write accepted entries plus a review report."""

    service = orchestrator or ReconstructionOrchestrator()
    references = load_bibliography_fragments(
        input_path.read_text(encoding="utf-8")
    )
    logger.info("loaded bibliography fragments count=%d", len(references))

    results: list[ProcessedReference | None] = [None] * len(references)
    with ThreadPoolExecutor(max_workers=settings.max_parallel_requests) as executor:
        future_to_index = {
            executor.submit(
                service.reconstruct_reference,
                InputData(parsed_data=reference),
            ): index
            for index, reference in enumerate(references)
        }
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            results[index] = future.result()

    processed = [result for result in results if result is not None]
    entries = [
        result.reconstructed_bibtex.strip()
        for result in processed
        if (
            result.outcome == ReconstructionOutcome.READY
            and result.reconstructed_bibtex
        )
    ]
    reviews = [
        result
        for result in processed
        if result.outcome == ReconstructionOutcome.MANUAL_REVIEW
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_text = "\n\n".join(entries)
    if output_text:
        output_text += "\n"
    output_path.write_text(output_text, encoding="utf-8")

    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_payload = {
        "schema_version": "1",
        "input": str(input_path),
        "bibtex_output": str(output_path),
        "total_fragments": len(processed),
        "reconstructed_count": len(entries),
        "manual_review_count": len(reviews),
        "manual_review": [
            result.model_dump(mode="json", exclude_none=True)
            for result in reviews
        ],
    }
    review_path.write_text(
        json.dumps(review_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return entries, reviews


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Reconstruct a damaged BibTeX file into Rust-validated entries. "
            "Unresolved fragments are written to a separate review report."
        )
    )
    parser.add_argument("input", type=Path, help="Damaged input .bib file")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("reconstructed.bib"),
        help="Rust-validated BibTeX output",
    )
    parser.add_argument(
        "--review-output",
        type=Path,
        default=Path("reconstruction-review.json"),
        help="Evidence and diagnostics for unresolved fragments",
    )
    parser.add_argument(
        "--fail-on-review",
        action="store_true",
        help="Exit with status 2 when any fragment requires manual review",
    )
    return parser


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = build_parser().parse_args()
    entries, reviews = reconstruct_file(
        args.input,
        args.output,
        args.review_output,
    )
    logger.info(
        "initialization completed reconstructed=%d manual_review=%d output=%s",
        len(entries),
        len(reviews),
        args.output,
    )
    if args.fail_on_review and reviews:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

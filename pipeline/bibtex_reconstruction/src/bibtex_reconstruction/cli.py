"""Standalone command-line entry point for bibliography initialization."""

from __future__ import annotations

import argparse
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .application.orchestrator import ReconstructionOrchestrator
from .application.key_generation import CitationKeyGenerator
from .application.source_loader import load_metadata_document
from .config import settings
from .domain import InputData, ProcessedReference, ReconstructionReport
from .domain.enums import ReconstructionOutcome
from .logging_config import configure_logging


logger = logging.getLogger(__name__)


def reconstruct_file(
    input_path: Path,
    output_path: Path,
    report_path: Path,
    *,
    orchestrator: ReconstructionOrchestrator | None = None,
    key_generator: CitationKeyGenerator | None = None,
    reference_threads: int | None = None,
    api_threads: int | None = None,
) -> tuple[list[str], ReconstructionReport]:
    """Reconstruct all extracted references and write BibTeX plus an audit report."""

    document = load_metadata_document(input_path)
    references = document.references
    effective_reference_threads = (
        reference_threads or settings.reference_threads
    )
    effective_api_threads = api_threads or settings.api_threads
    service = orchestrator or ReconstructionOrchestrator(
        search_workers=effective_api_threads,
    )
    logger.info(
        "loaded extracted references count=%d reference_threads=%d api_threads=%d",
        len(references),
        effective_reference_threads,
        effective_api_threads,
    )

    results: list[ProcessedReference | None] = [None] * len(references)
    with ThreadPoolExecutor(max_workers=effective_reference_threads) as executor:
        future_to_index = {
            executor.submit(
                service.reconstruct_reference,
                InputData(parsed_data=reference),
            ): index
            for index, reference in enumerate(references)
        }
        for completed_count, future in enumerate(
            as_completed(future_to_index),
            start=1,
        ):
            index = future_to_index[future]
            result = future.result()
            results[index] = result
            logger.info(
                "progress=%d/%d ref_id=%s outcome=%s path=%s",
                completed_count,
                len(references),
                result.ref_id,
                result.outcome.value,
                (
                    result.reconstruction_path.value
                    if result.reconstruction_path
                    else "none"
                ),
            )

    processed = [result for result in results if result is not None]
    (key_generator or CitationKeyGenerator()).apply(processed)
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

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = ReconstructionReport(
        input_path=input_path,
        bibtex_output_path=output_path,
        document=document.document_metadata(),
        total_reference_count=len(processed),
        reconstructed_count=len(entries),
        manual_review_count=len(reviews),
        processed_references=processed,
    )
    report_path.write_text(
        json.dumps(
            report.model_dump(mode="json", exclude_none=True),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return entries, report


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Reconstruct metadata_extraction JSON references into "
            "Rust-validated BibTeX entries and an audit report."
        )
    )
    parser.add_argument(
        "input",
        type=Path,
        help="metadata_extraction JSON file",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=Path("reconstructed.bib"),
        help="Rust-validated BibTeX output",
    )
    parser.add_argument(
        "--report-output",
        "--review-output",
        dest="report_output",
        type=Path,
        default=Path("reconstruction-report.json"),
        help="Audit report with outcomes and evidence for every reference",
    )
    parser.add_argument(
        "--fail-on-review",
        action="store_true",
        help="Exit with status 2 when any reference requires manual review",
    )
    parser.add_argument(
        "--threads",
        "--reference-threads",
        dest="reference_threads",
        type=_positive_int,
        default=settings.reference_threads,
        help=(
            "Concurrent reference workers "
            f"(default: {settings.reference_threads})"
        ),
    )
    parser.add_argument(
        "--api-threads",
        type=_positive_int,
        default=settings.api_threads,
        help=(
            "Concurrent provider searches per reference "
            f"(default: {settings.api_threads})"
        ),
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        help="Detailed execution log file (DEBUG and above)",
    )
    parser.add_argument(
        "--log-level",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
        default="INFO",
        help="Console log level (default: INFO)",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    configure_logging(
        console_level=args.log_level,
        log_file=args.log_file,
    )
    logger.info(
        "initialization started input=%s references_output=%s report_output=%s",
        args.input,
        args.output,
        args.report_output,
    )
    if args.log_file:
        logger.info("detailed log=%s", args.log_file)
    entries, report = reconstruct_file(
        args.input,
        args.output,
        args.report_output,
        reference_threads=args.reference_threads,
        api_threads=args.api_threads,
    )
    logger.info(
        "initialization completed reconstructed=%d manual_review=%d output=%s",
        len(entries),
        report.manual_review_count,
        args.output,
    )
    if args.fail_on_review and report.manual_review_count:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

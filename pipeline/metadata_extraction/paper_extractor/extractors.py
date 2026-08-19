from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable

from .models import ExtractionResult, PaperMetadata, Reference
from .paddleocr_vl import (
    load_paddleocr_vl_artifact,
    parse_paddleocr_vl_payload,
    run_paddleocr_vl,
)

PADDLEOCR_VL_COMMAND_ENV = "PADDLEOCR_VL_COMMAND"
DEFAULT_EXTRACTION_JOBS = 2


class ExtractionError(RuntimeError):
    """Raised when PaddleOCR-VL extraction cannot produce a result."""


@dataclass(slots=True)
class ExtractionConfig:
    paddleocr_vl_json: Path | None = None
    paddleocr_vl_command: str | None = None
    paddleocr_vl_device: str | None = None
    paddleocr_vl_engine: str | None = None
    paddleocr_vl_rec_backend: str | None = None
    paddleocr_vl_rec_server_url: str | None = None
    paddleocr_vl_rec_api_model_name: str | None = None
    paddleocr_vl_rec_api_key: str | None = None
    save_dir: Path | None = None


def extract_paper(
    pdf_path: str | Path,
    config: ExtractionConfig | None = None,
) -> ExtractionResult:
    pdf = Path(pdf_path)
    cfg = config or ExtractionConfig()
    if not pdf.exists():
        raise ExtractionError(f"Input PDF does not exist: {pdf}")
    if not pdf.is_file():
        raise ExtractionError(f"Input path is not a file: {pdf}")

    try:
        metadata, references, saved_files = _extract_paddleocr_vl(cfg, pdf)
    except Exception as exc:
        raise ExtractionError(str(exc)) from exc

    result = ExtractionResult(
        input_pdf=pdf,
        metadata=metadata,
        references=references,
        saved_files=saved_files,
    )
    if cfg.save_dir:
        try:
            result.saved_files.append(_write_normalized_output(cfg.save_dir, result))
        except OSError as exc:
            raise ExtractionError(f"Could not save extraction files for {pdf}: {exc}") from exc
    return result


def extract_papers(
    pdf_paths: Iterable[str | Path],
    config: ExtractionConfig | None = None,
    *,
    jobs: int = DEFAULT_EXTRACTION_JOBS,
) -> list[ExtractionResult]:
    """Extract multiple PDFs concurrently while preserving input order.

    Batch runs isolate saved artifacts below one subdirectory per PDF. A
    normalized artifact supplied with ``paddleocr_vl_json`` is inherently tied
    to one PDF and therefore cannot be reused for a batch.
    """

    if jobs < 1:
        raise ValueError("jobs must be at least 1")

    pdfs = [Path(path) for path in pdf_paths]
    if not pdfs:
        return []

    cfg = config or ExtractionConfig()
    if len(pdfs) == 1:
        return [extract_paper(pdfs[0], config=cfg)]
    if cfg.paddleocr_vl_json is not None:
        raise ExtractionError("--paddleocr-vl-json can only be used with one PDF.")

    _validate_batch_save_paths(pdfs, cfg.save_dir)
    results: list[ExtractionResult | None] = [None] * len(pdfs)
    failures: list[tuple[int, ExtractionError]] = []
    max_workers = min(jobs, len(pdfs))

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {
            executor.submit(
                extract_paper,
                pdf,
                config=_config_for_batch_pdf(cfg, pdf),
            ): index
            for index, pdf in enumerate(pdfs)
        }
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            try:
                results[index] = future.result()
            except ExtractionError as exc:
                failures.append((index, exc))

    if failures:
        failures.sort(key=lambda item: item[0])
        details = "\n".join(f"- {pdfs[index]}: {error}" for index, error in failures)
        raise ExtractionError(f"Extraction failed for {len(failures)} PDF(s):\n{details}")

    return [result for result in results if result is not None]


def _validate_batch_save_paths(pdfs: list[Path], save_dir: Path | None) -> None:
    if save_dir is None:
        return
    stems = [pdf.stem for pdf in pdfs]
    duplicates = sorted(stem for stem, count in Counter(stems).items() if count > 1)
    if duplicates:
        names = ", ".join(duplicates)
        raise ExtractionError(
            "Batch inputs must have unique file stems when --save-dir is used; "
            f"duplicates: {names}."
        )


def _config_for_batch_pdf(config: ExtractionConfig, pdf: Path) -> ExtractionConfig:
    save_dir = config.save_dir / pdf.stem if config.save_dir is not None else None
    return replace(config, save_dir=save_dir)


def _extract_paddleocr_vl(
    config: ExtractionConfig,
    pdf: Path,
) -> tuple[PaperMetadata, list[Reference], list[Path]]:
    if config.paddleocr_vl_json is not None:
        metadata, references = load_paddleocr_vl_artifact(config.paddleocr_vl_json)
        return metadata, references, []

    command = config.paddleocr_vl_command or os.environ.get(PADDLEOCR_VL_COMMAND_ENV)
    if command:
        return _run_paddleocr_vl_command(command, pdf, config)

    metadata, references, saved_files = run_paddleocr_vl(
        pdf,
        device=config.paddleocr_vl_device,
        engine=config.paddleocr_vl_engine,
        vl_rec_backend=config.paddleocr_vl_rec_backend,
        vl_rec_server_url=config.paddleocr_vl_rec_server_url,
        vl_rec_api_model_name=config.paddleocr_vl_rec_api_model_name,
        vl_rec_api_key=config.paddleocr_vl_rec_api_key,
        save_dir=config.save_dir,
    )
    return metadata, references, saved_files


def _run_paddleocr_vl_command(
    command: str,
    pdf: Path,
    config: ExtractionConfig,
) -> tuple[PaperMetadata, list[Reference], list[Path]]:
    command_parts = shlex.split(command)
    if not command_parts:
        raise ExtractionError("PaddleOCR-VL command is empty.")
    if shutil.which(command_parts[0]) is None:
        raise ExtractionError(f"PaddleOCR-VL command is not executable: {command_parts[0]}")

    with tempfile.TemporaryDirectory(prefix="bibmgr-paddleocr-vl-") as temp_dir:
        output_path = Path(temp_dir) / "paddleocr-vl.json"
        completed = subprocess.run(
            [*command_parts, str(pdf), "--output", str(output_path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise ExtractionError(f"PaddleOCR-VL command failed: {detail}")
        payload_text = output_path.read_text(encoding="utf-8") if output_path.exists() else completed.stdout

    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise ExtractionError("PaddleOCR-VL command did not return valid JSON.") from exc

    metadata, references = parse_paddleocr_vl_payload(payload)
    saved_files: list[Path] = []
    if config.save_dir:
        config.save_dir.mkdir(parents=True, exist_ok=True)
        raw_path = config.save_dir / f"{pdf.stem}.paddleocr-vl.raw.json"
        raw_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        saved_files.append(raw_path)
    return metadata, references, saved_files


def _write_normalized_output(save_dir: Path, result: ExtractionResult) -> Path:
    save_dir.mkdir(parents=True, exist_ok=True)
    output_path = save_dir / f"{result.input_pdf.stem}.paper_extraction.json"
    output_path.write_text(
        json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_path

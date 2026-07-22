#!/usr/bin/env python3
"""Assert CLI JSON, PyO3, and backend DTO parity on shared fixtures."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import tempfile
from typing import Any

import bibmgr_native
from bibmgr_backend.native import NativeEngine


FIXTURES = {
    "valid": """@article{vaswani-attention,
  author = {Vaswani, Ashish and others},
  title = {Attention Is All You Need},
  journal = {arXiv:1706.03762},
  year = {2017},
}
""",
    "unicode": """% 日本語のコメント
@inproceedings{yamada-解析,
  author = {山田, 太郎},
  title = {構文解析の研究},
  booktitle = {Annual Meeting of ACL},
  year = {2026},
}
""",
    "recoverable": """@article{partial,
  title = {An unfinished entry},
  author = {Example, Alice}
""",
}

EXPORT_SOURCE = """@misc{smith-2024,
  title = {Profile-Aware Export},
  author = {Smith, Jane},
  year = {2024},
  eprint = {2401.00001},
  archivePrefix = {arXiv},
  primaryClass = {cs.DL},
  doi = {10.5555/example},
  url = {https://arxiv.org/abs/2401.00001},
  abstract = {Adapter-only fields must follow the output profile.},
  customfield = {Not accepted by restricted profiles},
}
"""

EXPORT_PROFILES = (
    "modern",
    "laboratory",
    "acl",
    "aaai",
    "classical-bst",
    "legacy-arxiv-article",
)


def cli_analysis(cli: Path, source: str, profile: str) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="", suffix=".bib"
    ) as fixture:
        fixture.write(source)
        fixture.flush()
        completed = subprocess.run(
            [
                str(cli),
                "lint",
                fixture.name,
                "--format",
                "json",
                "--profile",
                profile,
                "--tolerant",
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    if completed.returncode not in (0, 1):
        raise RuntimeError(
            f"CLI failed with {completed.returncode}: {completed.stderr.strip()}"
        )
    return json.loads(completed.stdout)


def cli_export(cli: Path, source: str, profile: str) -> dict[str, Any]:
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="", suffix=".bib"
    ) as fixture:
        fixture.write(source)
        fixture.flush()
        completed = subprocess.run(
            [
                str(cli),
                "export",
                fixture.name,
                "--format",
                "json",
                "--profile",
                profile,
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    if completed.returncode != 0:
        raise RuntimeError(
            f"CLI export for {profile} failed with {completed.returncode}: "
            f"{completed.stderr.strip()}"
        )
    return json.loads(completed.stdout)


def assert_parity(cli: Path, profile: str) -> None:
    backend = NativeEngine(bibmgr_native)
    for name, source in FIXTURES.items():
        cli_dto = cli_analysis(cli, source, profile)
        python_dto = bibmgr_native.analyze(
            source, profile=profile, tolerant=True
        ).to_dict()
        backend_dto = backend.analyze(source, profile=profile, mode="tolerant")

        if cli_dto != python_dto:
            raise AssertionError(
                f"{name}: CLI/PyO3 mismatch\n"
                f"CLI: {json.dumps(cli_dto, ensure_ascii=False, sort_keys=True)}\n"
                f"PyO3: {json.dumps(python_dto, ensure_ascii=False, sort_keys=True)}"
            )
        if backend_dto != python_dto:
            raise AssertionError(f"{name}: backend/PyO3 DTO mismatch")

    for export_profile in EXPORT_PROFILES:
        cli_dto = cli_export(cli, EXPORT_SOURCE, export_profile)
        python_dto = bibmgr_native.export_source(
            EXPORT_SOURCE, profile=export_profile
        ).to_dict()
        backend_dto = backend.export_source(EXPORT_SOURCE, profile=export_profile)

        if cli_dto != python_dto:
            raise AssertionError(
                f"export {export_profile}: CLI/PyO3 mismatch\n"
                f"CLI: {json.dumps(cli_dto, ensure_ascii=False, sort_keys=True)}\n"
                f"PyO3: {json.dumps(python_dto, ensure_ascii=False, sort_keys=True)}"
            )
        if backend_dto != python_dto:
            raise AssertionError(
                f"export {export_profile}: backend/PyO3 DTO mismatch"
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cli",
        type=Path,
        default=Path("target/debug/bibmgr"),
        help="path to the built bibmgr executable",
    )
    parser.add_argument("--profile", default="laboratory")
    arguments = parser.parse_args()

    if not arguments.cli.is_file():
        parser.error(f"CLI executable does not exist: {arguments.cli}")
    assert_parity(arguments.cli.resolve(), arguments.profile)
    print(
        "CLI, PyO3, and backend parity passed for "
        f"{len(FIXTURES)} analysis fixtures and {len(EXPORT_PROFILES)} export profiles"
    )


if __name__ == "__main__":
    main()

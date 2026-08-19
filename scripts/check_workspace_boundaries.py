#!/usr/bin/env python3
"""Fail when crate dependencies bypass the architecture boundaries."""

from __future__ import annotations

from pathlib import Path
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[1]


def manifest(path: Path) -> dict[str, object]:
    with path.open("rb") as stream:
        return tomllib.load(stream)


def dependency_names(crate: str) -> set[str]:
    data = manifest(ROOT / "crates" / crate / "Cargo.toml")
    dependencies = data.get("dependencies", {})
    assert isinstance(dependencies, dict)
    return set(dependencies)


def main() -> int:
    errors: list[str] = []
    workspace = manifest(ROOT / "Cargo.toml").get("workspace", {})
    assert isinstance(workspace, dict)
    members = workspace.get("members", [])
    assert isinstance(members, list)
    if any(str(member).startswith("pipeline/") for member in members):
        errors.append("pipeline must not be a Cargo workspace member")

    for adapter in ("bibmgr-cli", "bibmgr-python"):
        internal = {
            name
            for name in dependency_names(adapter)
            if name.startswith("bibmgr-")
        }
        if internal != {"bibmgr-core"}:
            errors.append(
                f"{adapter} must depend only on bibmgr-core internally; got "
                f"{sorted(internal)}"
            )

    parser_users = [
        crate
        for crate in (
            "bibmgr-model",
            "bibmgr-syntax",
            "bibmgr-semantics",
            "bibmgr-validation",
            "bibmgr-edit",
            "bibmgr-export",
            "bibmgr-core",
            "bibmgr-cli",
            "bibmgr-python",
        )
        if "bibtex-parser" in dependency_names(crate)
    ]
    if parser_users != ["bibmgr-syntax"]:
        errors.append(
            "bibtex-parser must be isolated in bibmgr-syntax; got "
            f"{parser_users}"
        )

    if errors:
        print("\n".join(f"architecture error: {error}" for error in errors), file=sys.stderr)
        return 1
    print("workspace dependency boundaries are valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

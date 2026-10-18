#!/usr/bin/env python3
"""Build the general-purpose web-target WASM package; no browser-extension assets."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def build(output: Path) -> None:
    output = output.resolve()
    if output == ROOT or output in ROOT.parents:
        raise ValueError("Output must be a dedicated artifact directory")
    if output.exists() and not (output / "bibmgr_bg.wasm").is_file():
        raise ValueError("Refusing to replace an unrelated directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="bibmgr-wasm-", dir=output.parent) as folder:
        stage = Path(folder) / "wasm"
        subprocess.run(["wasm-pack", "build", "crates/bibmgr-wasm", "--target", "web", "--release",
                        "--out-dir", str(stage), "--out-name", "bibmgr", "--no-pack", "--", "--locked"], cwd=ROOT, check=True)
        subprocess.run(["node", str(ROOT / "scripts/check_wasm.mjs"), str(stage)], check=True)
        if output.exists():
            shutil.rmtree(output)
        shutil.move(str(stage), output)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/wasm")
    build(parser.parse_args().output)

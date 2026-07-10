#!/usr/bin/env python3
"""Generate all deterministic B2 baseline evidence packages."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from the_pass.engine.workflows import BASELINE_NAMES, run_baseline  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=ROOT / "examples" / "b2-baselines")
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    output_root = args.output_root.resolve()
    try:
        if args.clean and output_root.exists():
            shutil.rmtree(output_root)
        generated = [str(run_baseline(name, output_root / name / "package")) for name in BASELINE_NAMES]
        response = {"ok": True, "status": "complete", "artifact_paths": generated, "issues": [], "receipt_id": None}
        print(json.dumps(response, indent=2, sort_keys=True) if args.format == "json" else f"generated {len(generated)} B2 baseline packages")
        return 0
    except Exception as exc:
        response = {"ok": False, "status": "error", "artifact_paths": [], "issues": [{"path": str(output_root), "message": str(exc)}], "receipt_id": None}
        print(json.dumps(response) if args.format == "json" else f"B2 baseline generation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

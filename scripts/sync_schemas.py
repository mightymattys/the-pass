#!/usr/bin/env python3
"""Synchronize source JSON Schemas into the installed package tree."""

from __future__ import annotations

import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "schemas"
DESTINATION = ROOT / "src" / "the_pass" / "schemas"


def main() -> int:
    DESTINATION.mkdir(parents=True, exist_ok=True)
    source_files = {path.name: path for path in SOURCE.glob("*.json")}
    for packaged in DESTINATION.glob("*.json"):
        if packaged.name not in source_files:
            packaged.unlink()
    for name, source in sorted(source_files.items()):
        shutil.copy2(source, DESTINATION / name)
    print(f"synced {len(source_files)} schemas into {DESTINATION.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

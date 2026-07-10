"""Immutable raw JSON response archive for public provider reads."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from .contracts import canonical_value, stable_fingerprint


SAFE_NAME = re.compile(r"^[A-Za-z0-9._=-]+$")


class RawResponseArchive:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def store(self, *, provider: str, stream: str, received_at_ns: int, payload: Any) -> tuple[Path, str]:
        for value in (provider, stream):
            if not SAFE_NAME.fullmatch(value) or value in {".", ".."}:
                raise ValueError(f"unsafe archive segment: {value!r}")
        fingerprint = stable_fingerprint(payload)
        path = self.root / provider / stream / f"{received_at_ns}-{fingerprint}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(canonical_value(payload, allow_float=True), sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n"
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if path.read_bytes() != encoded:
                raise RuntimeError(f"raw archive fingerprint collision: {path}")
            return path, fingerprint
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        return path, fingerprint

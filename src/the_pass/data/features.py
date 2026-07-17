"""Small deterministic reference feature builder."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable

from .contracts import CanonicalEvent, EventType, stable_fingerprint


@dataclass(frozen=True)
class FeatureBuild:
    rows: list[dict[str, Any]]
    manifest: dict[str, Any]


def build_bar_features(
    events: Iterable[CanonicalEvent],
    *,
    dataset_fingerprint: str,
    code_version: str,
    config: dict[str, Any],
    created_at: str,
) -> FeatureBuild:
    if len(dataset_fingerprint) != 64 or any(char not in "0123456789abcdefABCDEF" for char in dataset_fingerprint):
        raise ValueError("dataset_fingerprint must be a SHA-256 hex digest")
    ordered = sorted(events, key=CanonicalEvent.sort_key)
    actual_fingerprint = stable_fingerprint(
        [event.as_dict() for event in ordered]
    )
    if actual_fingerprint != dataset_fingerprint.lower():
        raise ValueError("input events do not match dataset_fingerprint")
    bars = [event for event in ordered if event.event_type == EventType.BAR]
    if not bars:
        raise ValueError("bar feature build requires at least one bar")
    rows: list[dict[str, Any]] = []
    previous: dict[str, Decimal] = {}
    for event in bars:
        close = Decimal(str(event.payload["close"]))
        row = {
            "instrument_id": event.instrument_id,
            "event_time_ns": event.event_time_ns,
            "receive_time_ns": event.receive_time_ns,
            "close": format(close, "f"),
            "return_1": None,
        }
        if event.instrument_id in previous:
            row["return_1"] = format(close / previous[event.instrument_id] - Decimal(1), "f")
        previous[event.instrument_id] = close
        rows.append(row)
    output_fingerprint = stable_fingerprint(rows)
    manifest = {
        "schema_version": 2,
        "id": f"features-{output_fingerprint[:16]}",
        "created_at": created_at,
        "dataset_fingerprint": dataset_fingerprint,
        "code_version": code_version,
        "config_hash": stable_fingerprint(config),
        "features": ["close", "return_1"],
        "rows": len(rows),
        "output_fingerprint": output_fingerprint,
    }
    return FeatureBuild(rows=rows, manifest=manifest)

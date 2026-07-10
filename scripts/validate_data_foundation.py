#!/usr/bin/env python3
"""Validate D1 canonical data and public adapter evidence."""

from __future__ import annotations

import json
import sys
import tempfile
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from the_pass.adapters import DatabentoCompatibleFuturesAdapter, FetchRequest, ReadOnlyAdapter  # noqa: E402
from the_pass.data import (  # noqa: E402
    QualityPolicy,
    build_bar_features,
    build_instrument_registry,
    build_quality_report,
    stable_fingerprint,
)
from the_pass.validator import validate_artifact  # noqa: E402


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    required = (
        "src/the_pass/data/contracts.py",
        "src/the_pass/data/quality.py",
        "src/the_pass/data/storage.py",
        "src/the_pass/data/query.py",
        "src/the_pass/data/raw_archive.py",
        "src/the_pass/adapters/base.py",
        "src/the_pass/adapters/binance_spot.py",
        "src/the_pass/adapters/databento_futures.py",
        "src/the_pass/adapters/polymarket.py",
        "tests/fixtures/futures/instrument_definitions.json",
        "tests/fixtures/futures/events.json",
        "reports/gates/D1_public_smoke_2026-07-10.json",
    )
    missing = [relative for relative in required if not (ROOT / relative).is_file()]
    if missing:
        fail("missing D1 evidence: " + ", ".join(missing))

    smoke = json.loads((ROOT / "reports/gates/D1_public_smoke_2026-07-10.json").read_text(encoding="utf-8"))
    for lane in ("binance", "polymarket", "futures_fixture"):
        if smoke.get(lane, {}).get("status") != "pass":
            fail(f"D1 smoke lane did not pass: {lane}")
    safety = smoke.get("safety", {})
    if any(safety.get(field) is not False for field in ("authenticated_channels_used", "credentials_used", "writes_to_provider")):
        fail("D1 public smoke crossed a read-only safety boundary")

    adapter = DatabentoCompatibleFuturesAdapter(ROOT / "tests" / "fixtures" / "futures")
    if not isinstance(adapter, ReadOnlyAdapter):
        fail("futures adapter does not satisfy ReadOnlyAdapter protocol")
    raw = adapter.fetch_raw(FetchRequest(kind="bars"))
    events = adapter.normalize(raw, FetchRequest(kind="bars"), receive_time_ns=1)
    report = build_quality_report(
        "d1-fixture",
        events,
        policy=QualityPolicy(expected_interval_ns=60_000_000_000),
        created_at="2026-07-10T00:00:00Z",
    )
    if report["promotion_impact"] != "none":
        fail("clean D1 futures fixture did not pass quality checks")
    fingerprint = stable_fingerprint([event.as_dict() for event in events])
    left = build_bar_features(
        events,
        dataset_fingerprint=fingerprint,
        code_version="d1-gate",
        config={"return_window": 1},
        created_at="2026-07-10T00:00:00Z",
    )
    right = build_bar_features(
        reversed(events),
        dataset_fingerprint=fingerprint,
        code_version="d1-gate",
        config={"return_window": 1},
        created_at="2026-07-10T00:00:00Z",
    )
    if left != right:
        fail("D1 feature build is not deterministic")
    if Decimal(left.rows[-1]["return_1"]) <= 0:
        fail("D1 fixture feature output is unexpected")

    registry = build_instrument_registry(
        "d1-fixture",
        "databento-compatible-futures",
        adapter.discover_instruments(),
        created_at="2026-07-10T00:00:00Z",
    )
    artifacts = {
        "canonical_event": events[0].as_dict(),
        "instrument_registry": registry,
        "quality_report": report,
        "feature_manifest": left.manifest,
    }
    with tempfile.TemporaryDirectory() as tmp:
        for artifact_type, document in artifacts.items():
            path = Path(tmp) / f"{artifact_type}.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            result = validate_artifact(path, artifact_type=artifact_type)
            if not result.ok:
                fail(f"generated D1 artifact does not validate: {artifact_type}")

    print("data foundation validation passed: 3 adapter lanes, deterministic features, read-only smoke")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

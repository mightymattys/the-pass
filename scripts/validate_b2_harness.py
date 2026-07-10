#!/usr/bin/env python3
"""Validate B2 simulator, baseline packages, and reproducibility evidence."""

from __future__ import annotations

import hashlib
import json
import math
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from the_pass.engine.fills import DiagnosticMidpointFillModel  # noqa: E402
from the_pass.engine.workflows import BASELINE_NAMES, run_baseline  # noqa: E402
from the_pass.ledger import verify_ledger_file  # noqa: E402
from the_pass.validator import validate_package  # noqa: E402


EXPECTED_VARIANTS = {
    "buy_hold": 1,
    "seeded_random": 1,
    "donchian_momentum": 3,
    "mean_reversion": 3,
    "futures_trend": 2,
    "prediction_complement": 1,
}
CORE_REPRO_FILES = (
    "strategy_spec.json",
    "data_manifest.json",
    "quality_report.json",
    "run_receipt.json",
    "metrics_report.json",
    "cost_waterfall.json",
    "verdict_report.json",
    "search_space.json",
    "runner_result.json",
    "screen_results.json",
    "run_report.md",
    "run_report.html",
)


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    baseline_root = ROOT / "examples" / "b2-baselines"
    if tuple(EXPECTED_VARIANTS) != BASELINE_NAMES:
        fail("B2 expected baseline registry differs from public workflow")
    for name, expected_variants in EXPECTED_VARIANTS.items():
        package = baseline_root / name / "package"
        result = validate_package(package)
        if not result.ok:
            fail(f"B2 package does not validate: {name}")
        ledger_issues = verify_ledger_file(package / "receipt-ledger.jsonl")
        if ledger_issues:
            fail(f"B2 ledger does not verify: {name}")
        search = json.loads((package / "search_space.json").read_text(encoding="utf-8"))
        screen = json.loads((package / "screen_results.json").read_text(encoding="utf-8"))
        if len(search["variants"]) != expected_variants or len(screen) != expected_variants:
            fail(f"B2 variant coverage mismatch: {name}")
        metrics = json.loads((package / "metrics_report.json").read_text(encoding="utf-8"))
        costs = json.loads((package / "cost_waterfall.json").read_text(encoding="utf-8"))
        expected_net = costs["gross_pnl"] - sum(value for value in costs["costs"].values() if value is not None)
        if not math.isclose(costs["net_pnl"], expected_net, rel_tol=1e-12, abs_tol=1e-12):
            fail(f"B2 cost identity mismatch: {name}")
        if metrics["net_metrics"]["pnl"] != costs["net_pnl"]:
            fail(f"B2 metrics and waterfall disagree: {name}")
        html = (package / "run_report.html").read_text(encoding="utf-8")
        if "<form" in html.lower() or "No promotion or live capability" not in html:
            fail(f"B2 static report is not read-only: {name}")

    random_package = baseline_root / "seeded_random" / "package"
    random_metrics = json.loads((random_package / "metrics_report.json").read_text(encoding="utf-8"))
    random_verdict = json.loads((random_package / "verdict_report.json").read_text(encoding="utf-8"))
    if random_metrics["net_metrics"]["pnl"] >= 0 or random_verdict["verdict"] != "kill":
        fail("seeded random baseline must be net-negative and killed")
    if DiagnosticMidpointFillModel().promotion_eligible:
        fail("diagnostic midpoint fill must never support promotion")

    with tempfile.TemporaryDirectory() as tmp:
        reproduced = run_baseline("buy_hold", Path(tmp) / "package")
        tracked = baseline_root / "buy_hold" / "package"
        for name in CORE_REPRO_FILES:
            if digest(reproduced / name) != digest(tracked / name):
                fail(f"B2 clean-run fingerprint mismatch: {name}")

    print("B2 harness validation passed: 6 packages, 11 variants, deterministic clean replay")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

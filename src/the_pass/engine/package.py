"""Create complete, immutable-style B2 baseline evidence packages."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from the_pass.data.contracts import CanonicalEvent, canonical_value, stable_fingerprint
from the_pass.data.quality import QualityPolicy, build_quality_report
from the_pass.ledger import append_ledger_entry
from the_pass.validator import validate_package

from .contracts import RunnerResult
from .reporting import build_metrics_and_costs, render_html, render_markdown


def _time(value_ns: int) -> str:
    return datetime.fromtimestamp(value_ns / 1_000_000_000, tz=timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _json(path: Path, document: object) -> None:
    _write(path, json.dumps(canonical_value(document, allow_float=True), indent=2, sort_keys=True) + "\n")


def preregister_search_space(output_dir: Path, search_space: dict[str, Any]) -> Path:
    package = output_dir.resolve()
    package.mkdir(parents=True, exist_ok=True)
    path = package / "search_space.json"
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if existing != canonical_value(search_space):
            raise FileExistsError(f"different search space is already registered: {path}")
        return path
    if any(package.iterdir()):
        raise FileExistsError(f"run package directory is not empty: {package}")
    _json(path, search_space)
    return path


def strategy_spec(strategy_id: str, instrument_id: str, asset_class: str, search_space: dict[str, Any]) -> dict[str, Any]:
    prediction = asset_class == "prediction_market"
    return {
        "schema_version": 2,
        "id": strategy_id,
        "name": strategy_id.replace("_", " ").title(),
        "status": "research",
        "owner": "strategy_implementer",
        "created_at": "2026-07-10",
        "market": {"asset_class": asset_class, "venues": ["synthetic"], "instruments": [instrument_id], "timeframes": ["1m"]},
        "edge": {
            "primary_family": "baseline",
            "secondary_tags": ["diagnostic", "control"],
            "thesis": "Measure reference behavior under explicit costs before evaluating promotion candidates.",
            "why_now": "B2 harness accounting and execution validation.",
            "expected_failure_modes": ["cost drag", "small sample", "synthetic regime dependence"],
        },
        "data": {
            "required_sources": ["the-pass deterministic synthetic fixture"],
            "required_fields": ["event_time_ns", "receive_time_ns", "bids", "asks", "hash"] if prediction else ["event_time_ns", "receive_time_ns", "open", "high", "low", "close", "volume"],
            "minimum_history": "96 one-minute bars",
            "manifest_path": "data_manifest.json",
        },
        "signal": {
            "inputs": ["complementary outcome books"] if prediction else ["canonical bars"],
            "transforms": ["complement ask sum diagnostic"] if prediction else ["strategy-specific deterministic baseline transform"],
            "decision_time_policy": "decide only after receive_time; fill on subsequent bar",
            "lookahead_controls": ["no same-event fills", "deterministic event ordering"],
        },
        "execution": {
            "order_type": "paper_only",
            "fill_model": "next bar open with conservative slippage",
            "latency_assumption_ms": 1,
            "fee_model": "0.10 percent per fill",
            "slippage_model": "5 basis points adverse",
        },
        "risk": {
            "sizing_rule": "fixed one-unit target",
            "max_exposure": "one unit",
            "max_drawdown": "diagnostic only",
            "kill_switches": ["accounting identity failure", "invalid data quality"],
        },
        "validation": {
            "train_test_split": "diagnostic full sample",
            "holdout_policy": "promotion prohibited until V3",
            "null_baselines": ["seeded random control"],
            "parameter_sweeps": [search_space],
            "required_metrics": ["net pnl", "sharpe", "max drawdown", "turnover", "trade count"],
        },
        "gates": {
            "research_gate": ["complete B2 package", "cost waterfall", "V3 robustness pending"],
            "paper_gate": ["not eligible before V3"],
            "live_gate": ["blocked by public core"],
        },
        "done_when": ["deterministic package validates and ledger entry verifies"],
        "kill_when": ["accounting identity fails", "random control shows systematic repeatable net edge"],
        "notes": "StrategySpec copy is immutable after this run; changes require a new ID.",
    }


def write_run_package(
    output_dir: Path,
    *,
    result: RunnerResult,
    events: Iterable[CanonicalEvent],
    search_space: dict[str, Any],
    initial_cash: Decimal,
    asset_class: str,
    random_seed: int | None,
    verdict: str = "blocked",
    screen_results: list[dict[str, Any]] | None = None,
) -> Path:
    package = output_dir.resolve()
    registered_path = package / "search_space.json"
    if package.exists() and any(path.name != "search_space.json" for path in package.iterdir()):
        raise FileExistsError(f"run package directory contains artifacts other than preregistered search space: {package}")
    package.mkdir(parents=True, exist_ok=True)
    if not registered_path.is_file():
        raise ValueError("search space must be preregistered before the run")
    if json.loads(registered_path.read_text(encoding="utf-8")) != canonical_value(search_space):
        raise ValueError("registered search space differs from run configuration")
    rows = sorted(events, key=CanonicalEvent.sort_key)
    if not rows:
        raise ValueError("run package requires events")
    created_at = "2026-07-10T00:00:00Z"
    start_time = _time(rows[0].event_time_ns)
    end_time = _time(rows[-1].event_time_ns)
    dataset_fingerprint = stable_fingerprint([event.as_dict() for event in rows])
    quality = build_quality_report(
        result.strategy_id,
        rows,
        policy=QualityPolicy(expected_interval_ns=60_000_000_000),
        created_at=created_at,
    )
    if quality["promotion_impact"] == "blocked":
        raise ValueError("cannot package a run over blocked quality evidence")
    manifest = {
        "schema_version": 2,
        "id": f"{result.strategy_id}-data",
        "dataset_name": f"{result.strategy_id}-synthetic-bars",
        "created_at": created_at,
        "owner": "data_steward",
        "source": {
            "provider": "the-pass-synthetic",
            "venue": rows[0].venue,
            "endpoint_or_file": "deterministic in-process generator",
            "license_note": "MIT public synthetic fixture",
            "raw_path": "",
            "normalized_path": "",
        },
        "coverage": {
            "instruments": sorted({event.instrument_id for event in rows}),
            "start_time": start_time,
            "end_time": end_time,
            "timezone": "UTC",
            "event_time_field": "event_time_ns",
            "receive_time_field": "receive_time_ns",
        },
        "schema": {
            "fields": sorted(rows[0].as_dict()),
            "primary_keys": ["instrument_id", "event_time_ns", "sequence", "ingest_id"],
            "known_null_fields": [],
        },
        "quality": {
            "row_count": len(rows),
            "missing_intervals": [],
            "duplicate_policy": "duplicates block packaging",
            "sequence_gap_policy": "gaps block packaging",
            "cross_source_checks": ["synthetic generator fingerprint reproduced"],
        },
        "fingerprint": {"method": "sha256", "value": dataset_fingerprint},
        "limitations": ["synthetic diagnostic fixture"],
    }
    metrics, waterfall = build_metrics_and_costs(
        result,
        initial_cash=initial_cash,
        created_at=created_at,
        start_time=start_time,
        end_time=end_time,
    )
    spec = strategy_spec(result.strategy_id, rows[0].instrument_id, asset_class, search_space)
    receipt = {
        "schema_version": 2,
        "id": f"{result.strategy_id}-run",
        "created_at": created_at,
        "owner": "strategy_implementer",
        "strategy_spec": "strategy_spec.json",
        "code_version": "the-pass-0.4.0-b2",
        "data_manifest": "data_manifest.json",
        "command": f"the-pass backtest baseline --strategy {result.strategy_id}",
        "config_hash": stable_fingerprint(search_space),
        "random_seed": random_seed,
        "inputs": {"dataset_fingerprint": dataset_fingerprint, "search_space": "search_space.json"},
        "outputs": {
            "metrics_report": "metrics_report.json",
            "cost_waterfall": "cost_waterfall.json",
            "verdict_report": "verdict_report.json",
            "quality_report": "quality_report.json",
            "markdown_report": "run_report.md",
            "html_report": "run_report.html",
            "screen_results": "screen_results.json",
        },
        "safety": {"live_trading_enabled": False, "real_order_path_available": False, "credentials_available": False},
        "notes": "Deterministic public synthetic B2 baseline.",
    }
    verdict_document = {
        "schema_version": 2,
        "id": f"{result.strategy_id}-verdict",
        "run_receipt": "run_receipt.json",
        "created_at": created_at,
        "owner": "framework_auditor",
        "verdict": verdict,
        "summary": "B2 baseline completed; robustness and independent audit are not yet run.",
        "gate_results": {
            "universal_hard_gates": ["package validates", "accounting identities hold", "costs explicit"],
            "asset_class_gates": ["synthetic diagnostic only"],
            "failed_gates": ["V3 robustness and independent audit pending"],
        },
        "evidence": {
            "metrics_report": "metrics_report.json",
            "cost_waterfall": "cost_waterfall.json",
            "data_manifest": "data_manifest.json",
            "source_notes": [],
        },
        "risks": {
            "statistical": ["synthetic diagnostic sample"],
            "execution": ["next-bar model is not order-book replay"],
            "data": ["generated fixture"],
            "operational": ["no external process"],
        },
        "next_action": "Run V3 walk-forward, overfit diagnostics, stress, risk, and independent audit.",
        "review_required_by": ["stats_auditor", "execution_skeptic"],
    }
    if verdict == "kill":
        verdict_document["summary"] = "Seeded random control completed and is retained as a killed negative control."
        verdict_document["kill_reason"] = "Random direction has no mechanism and does not qualify for promotion."

    documents = {
        "strategy_spec.json": spec,
        "data_manifest.json": manifest,
        "quality_report.json": quality,
        "run_receipt.json": receipt,
        "metrics_report.json": metrics,
        "cost_waterfall.json": waterfall,
        "verdict_report.json": verdict_document,
        "runner_result.json": {
            "strategy_id": result.strategy_id,
            "events_processed": result.events_processed,
            "signals": result.signals,
            "fills": len(result.fills),
            "rejected": result.rejected,
            "missed": result.missed,
            "final_snapshot": result.final_snapshot,
            "cost_components": result.cost_components,
            "diagnostics": result.diagnostics,
        },
        "screen_results.json": screen_results or [],
    }
    for name, document in documents.items():
        _json(package / name, document)
    _write(package / "run_report.md", render_markdown(result.strategy_id, metrics, waterfall))
    _write(package / "run_report.html", render_html(result.strategy_id, metrics, waterfall))
    validation = validate_package(package)
    if not validation.ok:
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in validation.issues)
        raise RuntimeError(f"generated package failed validation: {details}")
    append_ledger_entry(package / "receipt-ledger.jsonl", package)
    return package

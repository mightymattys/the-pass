#!/usr/bin/env python3
"""Generate diagnostic P4 paper, automation, and dashboard evidence."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from the_pass.automation import run_automation_spec  # noqa: E402
from the_pass.data.contracts import canonical_value  # noqa: E402
from the_pass.engine.baselines import generate_synthetic_bars  # noqa: E402
from the_pass.paper import ObservationPolicy, build_paper_artifacts, run_virtual_paper_process  # noqa: E402
from the_pass.reporting import build_static_dashboard  # noqa: E402
from the_pass.risk import build_risk_policy_artifact  # noqa: E402
from the_pass.validator import validate_artifact  # noqa: E402


def write(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(canonical_value(document, allow_float=True), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "p4" / "synthetic_observation")
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    output = args.output.resolve()
    try:
        if args.clean and output.exists():
            shutil.rmtree(output)
        events = generate_synthetic_bars(instrument_id="BTCUSDT", profile="trend")
        policy = build_risk_policy_artifact("crypto_intraday")
        paper_result = run_virtual_paper_process(
            strategy_name="donchian_momentum",
            events=events,
            risk_policy=policy,
            observation_policy=ObservationPolicy(
                max_staleness_ns=300_000_000_000,
                max_clock_skew_ns=5_000_000_000,
                max_outage_gap_ns=120_000_000_000,
            ),
            observation_time_ns=events[-1].receive_time_ns,
            output_path=output / "paper_run.json",
        )
        package = ROOT / "examples" / "b2-baselines" / "donchian_momentum" / "package"
        metrics = json.loads((package / "metrics_report.json").read_text(encoding="utf-8"))
        costs = json.loads((package / "cost_waterfall.json").read_text(encoding="utf-8"))
        artifacts = build_paper_artifacts(
            source_package="../../../examples/b2-baselines/donchian_momentum/package",
            strategy_spec="../../../examples/b2-baselines/donchian_momentum/package/strategy_spec.json",
            adapter="binance-public-observer-diagnostic",
            config_hash=paper_result["config_hash"],
            instrument="BTCUSDT",
            paper_result=paper_result,
            backtest_metrics=metrics,
            backtest_costs=costs,
            start_time="2024-01-01T00:00:00Z",
            end_time="2024-01-01T01:35:00Z",
            observed_days=0,
            minimum_days=30,
            minimum_signals=500,
        )
        for artifact_type, document in artifacts.items():
            path = output / f"{artifact_type}.json"
            write(path, document)
            result = validate_artifact(path, artifact_type=artifact_type)
            if not result.ok:
                details = "; ".join(f"{issue.path}: {issue.message}" for issue in result.issues)
                raise RuntimeError(f"generated {artifact_type} failed validation: {details}")
        automation_document, automation_path = run_automation_spec(
            ROOT / "automations" / "data-health.yaml",
            output_dir=ROOT / "reports" / "automation",
            scheduled_for="2026-07-10T00:00:00Z",
            workspace_root=ROOT,
        )
        dashboard_paths = build_static_dashboard(ROOT, ROOT / "reports" / "dashboard")
        summary = {
            "schema_version": 1,
            "created_at": "2026-07-10T00:00:00Z",
            "paper_status": paper_result["status"],
            "process_isolated": paper_result["process_isolated"],
            "network_clients_loaded": paper_result["network_clients_loaded"],
            "credentials_present": paper_result["credentials_present"],
            "signals": paper_result["signals"],
            "fills": len(paper_result["fills"]),
            "divergence_decision": artifacts["divergence_report"]["decision"]["status"],
            "paper_gate": "blocked",
            "paper_gate_blockers": ["0 of 30 calendar days", f"{paper_result['signals']} of 500 signals"],
            "automation_run": str(automation_path.relative_to(ROOT)),
            "automation_status": automation_document["status"],
            "dashboard_files": [str(path.relative_to(ROOT)) for path in dashboard_paths],
        }
        write(output / "p4_summary.json", summary)
        response = {
            "ok": True,
            "status": "blocked",
            "artifact_paths": [str(output / name) for name in ("paper_run.json", "paper_plan.json", "observation_manifest.json", "divergence_report.json", "p4_summary.json")],
            "issues": [{"path": str(output / "divergence_report.json"), "message": "paper observation minimums are not met"}],
            "receipt_id": automation_document["id"],
        }
        print(json.dumps(response, indent=2, sort_keys=True) if args.format == "json" else "P4 diagnostic complete; paper gate remains blocked")
        return 2
    except Exception as exc:
        response = {"ok": False, "status": "error", "artifact_paths": [], "issues": [{"path": str(output), "message": str(exc)}], "receipt_id": None}
        print(json.dumps(response) if args.format == "json" else f"P4 diagnostic failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

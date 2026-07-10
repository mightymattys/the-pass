#!/usr/bin/env python3
"""Validate P4 paper, automation, incident, and static reporting capability."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from the_pass.automation import AUTOMATION_COMMANDS  # noqa: E402
from the_pass.reporting import DASHBOARD_VIEWS  # noqa: E402
from the_pass.validator import validate_artifact  # noqa: E402


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    paper_root = ROOT / "reports" / "p4" / "synthetic_observation"
    for name, artifact_type in (
        ("paper_plan.json", "paper_plan"),
        ("observation_manifest.json", "observation_manifest"),
        ("divergence_report.json", "divergence_report"),
    ):
        result = validate_artifact(paper_root / name, artifact_type=artifact_type)
        if not result.ok:
            fail(f"P4 artifact does not validate: {name}")
    paper = json.loads((paper_root / "paper_run.json").read_text(encoding="utf-8"))
    if paper["status"] != "complete" or not paper["process_isolated"]:
        fail("P4 virtual paper process did not complete in isolation")
    if paper["network_clients_loaded"] or paper["credentials_present"]:
        fail("P4 virtual paper process crossed its credential/network boundary")
    divergence = json.loads((paper_root / "divergence_report.json").read_text(encoding="utf-8"))
    for field in ("signal_divergence", "cost_divergence", "fill_divergence"):
        if divergence["comparisons"][field] != 0:
            fail(f"P4 synthetic parity diverged: {field}")
    if divergence["decision"]["status"] != "blocked":
        fail("P4 diagnostic observation must remain blocked")
    if not any("30 days" in breach["threshold"] and "500 signals" in breach["threshold"] for breach in divergence["breaches"]):
        fail("P4 paper minimum breach is missing")

    specs = sorted((ROOT / "automations").glob("*.yaml"))
    if len(specs) != len(AUTOMATION_COMMANDS):
        fail("P4 required automation spec count mismatch")
    commands = set()
    for path in specs:
        result = validate_artifact(path, artifact_type="automation_spec")
        if not result.ok:
            fail(f"P4 automation spec does not validate: {path.name}")
        import yaml

        commands.add(yaml.safe_load(path.read_text(encoding="utf-8"))["command"])
    if commands != set(AUTOMATION_COMMANDS):
        fail("P4 automation command coverage mismatch")
    run_paths = sorted((ROOT / "reports" / "automation").glob("automation-*.json"))
    if len(run_paths) != 1 or not validate_artifact(run_paths[0], artifact_type="automation_run").ok:
        fail("P4 automation receipt is missing or invalid")

    dashboard = ROOT / "reports" / "dashboard"
    expected = {"index.html", *(f"{view}.html" for view in DASHBOARD_VIEWS)}
    if {path.name for path in dashboard.glob("*.html")} != expected:
        fail("P4 dashboard view coverage mismatch")
    for path in dashboard.glob("*.html"):
        content = path.read_text(encoding="utf-8").lower()
        if any(token in content for token in ("<form", "<input", "fetch(")):
            fail(f"P4 dashboard is not read-only: {path.name}")
    summary = json.loads((paper_root / "p4_summary.json").read_text(encoding="utf-8"))
    if summary["paper_gate"] != "blocked" or summary["signals"] >= 500:
        fail("P4 summary overstates paper gate readiness")
    print("P4 framework validation passed: capability complete, paper gate correctly blocked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Validate the machine-readable trading roadmap without claiming incomplete work."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
STATUS_PATH = ROOT / "docs" / "implementation" / "roadmap-status.yaml"
PLAN_PATH = ROOT / "docs" / "implementation" / "TRADING_ROADMAP_EXECUTION_PLAN.md"
EXPECTED_ORDER = ["H0", "R0", "D1", "B2", "V3", "P4", "L5_L6"]
ALLOWED_STATUSES = {"not_started", "in_progress", "blocked", "gate_failed", "complete"}


def fail(message: str) -> None:
    print(f"roadmap validation failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    if not PLAN_PATH.is_file():
        fail(f"missing execution plan: {PLAN_PATH.relative_to(ROOT)}")
    if not STATUS_PATH.is_file():
        fail(f"missing roadmap status: {STATUS_PATH.relative_to(ROOT)}")

    document = yaml.safe_load(STATUS_PATH.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        fail("status document must be an object")
    if document.get("schema_version") != 1:
        fail("schema_version must be 1")
    if document.get("order") != EXPECTED_ORDER:
        fail(f"order must be {EXPECTED_ORDER}")
    if set(document.get("allowed_statuses", [])) != ALLOWED_STATUSES:
        fail("allowed_statuses does not match the roadmap contract")

    milestones = document.get("milestones")
    if not isinstance(milestones, list):
        fail("milestones must be an array")
    by_id = {item.get("id"): item for item in milestones if isinstance(item, dict)}
    if list(by_id) != EXPECTED_ORDER:
        fail("milestones must appear once in dependency order")

    completed: set[str] = set()
    for milestone_id in EXPECTED_ORDER:
        item = by_id[milestone_id]
        status = item.get("status")
        if status not in ALLOWED_STATUSES:
            fail(f"{milestone_id} has invalid status: {status}")
        dependencies = item.get("depends_on")
        if not isinstance(dependencies, list) or any(dep not in EXPECTED_ORDER for dep in dependencies):
            fail(f"{milestone_id} has invalid dependencies")
        if status in {"in_progress", "complete"} and any(dep not in completed for dep in dependencies):
            fail(f"{milestone_id} started before dependencies completed")

        evidence = item.get("evidence")
        if not isinstance(evidence, list):
            fail(f"{milestone_id}.evidence must be an array")
        if status == "complete":
            if item.get("gate_result") != "pass":
                fail(f"{milestone_id} is complete without gate_result: pass")
            if not evidence:
                fail(f"{milestone_id} is complete without evidence")
            for relative in evidence:
                if not isinstance(relative, str) or not (ROOT / relative).is_file():
                    fail(f"{milestone_id} evidence does not exist: {relative}")
            gate_relative = item.get("gate_evidence")
            if not isinstance(gate_relative, str) or not gate_relative:
                fail(f"{milestone_id} is complete without machine-readable gate evidence")
            gate_path = ROOT / gate_relative
            if not gate_path.is_file():
                fail(f"{milestone_id} gate evidence does not exist: {gate_relative}")
            gate = yaml.safe_load(gate_path.read_text(encoding="utf-8"))
            if not isinstance(gate, dict):
                fail(f"{milestone_id} gate evidence must be an object")
            if gate.get("milestone_id") != milestone_id or gate.get("gate_result") != "pass":
                fail(f"{milestone_id} gate evidence is not a pass for the same milestone")
            checks = gate.get("acceptance_checks")
            if not isinstance(checks, list) or not checks:
                fail(f"{milestone_id} gate evidence has no acceptance checks")
            for check in checks:
                if not isinstance(check, dict) or check.get("status") != "pass":
                    fail(f"{milestone_id} has a non-passing acceptance check")
                paths = check.get("evidence_paths")
                if not isinstance(paths, list) or not paths:
                    fail(f"{milestone_id} acceptance check has no evidence paths")
                for relative in paths:
                    if not isinstance(relative, str) or not (ROOT / relative).is_file():
                        fail(f"{milestone_id} acceptance evidence does not exist: {relative}")
            if gate.get("open_p0_p1") != []:
                fail(f"{milestone_id} gate has open P0/P1 findings")
            completed.add(milestone_id)

    print("roadmap validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

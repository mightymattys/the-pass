#!/usr/bin/env python3
"""Validate V3 robustness, risk, and independent audit evidence."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from the_pass.data.contracts import stable_fingerprint  # noqa: E402
from the_pass.validator import validate_artifact  # noqa: E402


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    root = ROOT / "reports" / "v3" / "donchian_momentum"
    required = {
        "robustness_report.json",
        "stress_report.json",
        "risk_policy.json",
        "risk_report.json",
        "stats_audit.json",
        "execution_audit.json",
        "reproduction_report.json",
    }
    missing = [name for name in sorted(required) if not (root / name).is_file()]
    if missing:
        fail("missing V3 artifacts: " + ", ".join(missing))
    for name, artifact_type in (
        ("risk_policy.json", "risk_policy"),
        ("risk_report.json", "risk_report"),
        ("stats_audit.json", "audit_report"),
        ("execution_audit.json", "audit_report"),
    ):
        result = validate_artifact(root / name, artifact_type=artifact_type)
        if not result.ok:
            fail(f"V3 artifact does not validate: {name}")

    robustness = json.loads((root / "robustness_report.json").read_text(encoding="utf-8"))
    for field in ("pbo", "psr", "dsr"):
        value = robustness["pbo"]["pbo"] if field == "pbo" else robustness[field]
        if not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            fail(f"V3 {field} is not a finite probability")
    if not robustness["anchored_walk_forward"] or not robustness["rolling_walk_forward"]:
        fail("V3 walk-forward evidence is empty")
    if not all(robustness["finite_probability_checks"].values()):
        fail("V3 finite probability checks did not pass")

    required_stress = {
        "fees_x1_5",
        "slippage_x2",
        "latency_x2",
        "depth_x0_5",
        "depth_x0_25",
        "maker_fill_probability_x0_5",
        "funding_worst_decile",
        "exchange_outage",
        "missing_interval",
        "correlated_gap",
        "forced_deleverage",
    }
    stress = json.loads((root / "stress_report.json").read_text(encoding="utf-8"))["scenarios"]
    if {item["scenario"] for item in stress} != required_stress:
        fail("V3 stress scenario coverage differs from policy")

    policy = json.loads((root / "risk_policy.json").read_text(encoding="utf-8"))
    core = {key: value for key, value in policy.items() if key != "policy_hash"}
    if stable_fingerprint(core) != policy["policy_hash"]:
        fail("V3 risk policy hash mismatch")
    report = json.loads((root / "risk_report.json").read_text(encoding="utf-8"))
    if report["policy_hash"] != policy["policy_hash"] or report["verdict"] != "blocked":
        fail("V3 risk report must bind exact policy and block the synthetic candidate")

    reviewers = set()
    for name in ("stats_audit.json", "execution_audit.json"):
        audit = json.loads((root / name).read_text(encoding="utf-8"))
        reviewers.add(audit["reviewer"])
        if audit["verdict"] != "blocked" or not any(item["blocks_promotion"] for item in audit["findings"]):
            fail(f"V3 independent audit did not block synthetic promotion: {name}")
        if any(item["severity"] in {"P0", "P1"} and item["status"] in {"open", "confirmed"} for item in audit["findings"]):
            fail(f"V3 framework gate has unresolved P0/P1 finding: {name}")
    if reviewers != {"stats_auditor", "execution_skeptic"}:
        fail("V3 independent reviewer roles are incomplete")

    reproduction = json.loads((root / "reproduction_report.json").read_text(encoding="utf-8"))
    if reproduction["status"] != "pass" or reproduction["mismatches"]:
        fail("V3 clean-room reproduction did not pass")
    candidate_verdict = json.loads(
        (ROOT / "examples" / "b2-baselines" / "donchian_momentum" / "package" / "verdict_report.json").read_text(encoding="utf-8")
    )
    if candidate_verdict["verdict"] != "blocked":
        fail("V3 must not promote the synthetic candidate")
    print("V3 audit validation passed: robustness complete, candidate correctly blocked")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

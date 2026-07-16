"""Pure candidate-assembly fingerprint contract shared by builder and validator."""

from __future__ import annotations

from typing import Any, Mapping

from .data.contracts import stable_fingerprint


def candidate_assembly_manifest(
    *,
    strategy: Mapping[str, Any],
    metrics: Mapping[str, Any],
    verdict: Mapping[str, Any],
    robustness: Mapping[str, Any],
    findings: Mapping[str, Any],
) -> dict[str, Any]:
    derived_fields = {
        "strategy_status": strategy.get("status"),
        "sample": {
            key: metrics.get("sample", {}).get(key)
            for key in (
                "evaluation_scope",
                "holdout_start_time",
                "holdout_end_time",
            )
        },
        "robustness": metrics.get("robustness"),
        "verdict": {
            "owner": verdict.get("owner"),
            "verdict": verdict.get("verdict"),
            "failed_gates": verdict.get("gate_results", {}).get("failed_gates"),
            "robustness_report": verdict.get("evidence", {}).get(
                "robustness_report"
            ),
        },
    }
    core = {
        "contract": "the-pass/candidate-assembly/v1",
        "source_package_id": robustness.get("source_package_id"),
        "robustness_report_fingerprint": robustness.get("report_fingerprint"),
        "findings_fingerprint": stable_fingerprint(findings),
        "derived_fields_fingerprint": stable_fingerprint(derived_fields),
    }
    return {**core, "assembly_fingerprint": stable_fingerprint(core)}

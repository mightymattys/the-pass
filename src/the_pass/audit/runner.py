"""Independent audit helpers with clean CLI reproduction."""

from __future__ import annotations

import hashlib
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence


REPRO_FILES = (
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


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reproduce_baseline_cli(name: str, tracked_package: Path) -> dict[str, Any]:
    baseline_name = name
    tracked_package = tracked_package.resolve()
    with tempfile.TemporaryDirectory() as tmp:
        package = Path(tmp) / "package"
        backtest = subprocess.run(
            [
                sys.executable,
                "-m",
                "the_pass.cli",
                "backtest",
                "baseline",
                "--name",
                baseline_name,
                "--output",
                str(package),
                "--format",
                "json",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        receipt = subprocess.run(
            [
                sys.executable,
                "-m",
                "the_pass.cli",
                "receipts",
                "verify",
                "--ledger",
                str(package / "receipt-ledger.jsonl"),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        mismatches = []
        fingerprints = []
        for artifact_name in REPRO_FILES:
            expected = _digest(tracked_package / artifact_name)
            observed = _digest(package / artifact_name) if (package / artifact_name).is_file() else None
            fingerprints.append({"path": artifact_name, "expected": expected, "observed": observed})
            if observed != expected:
                mismatches.append(artifact_name)
        return {
            "schema_version": 1,
            "created_at": "2026-07-10T00:00:00Z",
            "clean_temporary_directory": True,
            "commands": [
                f"python -m the_pass.cli backtest baseline --name {baseline_name} --output <temp>/package --format json",
                "python -m the_pass.cli receipts verify --ledger <temp>/package/receipt-ledger.jsonl",
            ],
            "backtest_exit_code": backtest.returncode,
            "receipt_exit_code": receipt.returncode,
            "fingerprints": fingerprints,
            "mismatches": mismatches,
            "status": "pass" if backtest.returncode == 0 and receipt.returncode == 0 and not mismatches else "blocked",
        }


def build_audit_report(
    *,
    report_id: str,
    target: str,
    owner: str,
    reviewer: str,
    findings: Sequence[dict[str, Any]],
    evidence: Sequence[str],
    limitations: Sequence[str],
) -> dict[str, Any]:
    if not reviewer or reviewer == owner:
        raise ValueError("audit reviewer must be independent from target owner")
    blocking = any(
        finding.get("blocks_promotion")
        and finding.get("status") in {"open", "confirmed"}
        for finding in findings
    )
    return {
        "schema_version": 2,
        "id": report_id,
        "created_at": "2026-07-10T00:00:00Z",
        "target": target,
        "reviewer": reviewer,
        "findings": list(findings),
        "verdict": "blocked" if blocking else "pass",
        "evidence": list(evidence),
        "limitations": list(limitations),
    }

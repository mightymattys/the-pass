"""Deterministic research-candidate package assembly."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .candidate_contract import candidate_assembly_manifest
from .ledger import build_run_entry
from .orchestration import create_superseding_package
from .validator import load_document, validate_artifact, validate_package


class CandidateAssemblyError(ValueError):
    """Raised when measured evidence cannot produce a valid candidate package."""


def _write_json_atomic(path: Path, document: dict[str, Any]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def _document(path: Path, *, artifact_type: str) -> dict[str, Any]:
    validation = validate_artifact(path, artifact_type=artifact_type)
    if not validation.ok:
        details = "; ".join(
            f"{issue.path}: {issue.message}" for issue in validation.issues
        )
        raise CandidateAssemblyError(
            f"{artifact_type} evidence is invalid: {details}"
        )
    document = load_document(path)
    if not isinstance(document, dict):
        raise CandidateAssemblyError(f"{artifact_type} evidence must be an object")
    return document


def assemble_research_candidate(
    source: Path,
    target: Path,
    *,
    ledger_path: Path,
    run_id: str,
    created_at: str,
    robustness_report_path: Path,
    findings_path: Path,
    trusted_registry_path: Path | None = None,
) -> tuple[Path, str]:
    """Create a validated successor from measured, independently reviewed evidence."""

    source = source.resolve()
    target = target.resolve()
    source_entry = build_run_entry(source, ledger_path=ledger_path)
    robustness = _document(
        robustness_report_path.resolve(), artifact_type="robustness_report"
    )
    findings = _document(findings_path.resolve(), artifact_type="findings")
    if robustness.get("source_package_id") != source_entry["package_id"]:
        raise CandidateAssemblyError(
            "robustness_report source_package_id does not match the source package"
        )
    if robustness.get("promotion_eligible") is not True:
        raise CandidateAssemblyError(
            "robustness_report is not promotion eligible"
        )
    if (
        findings.get("target_gate") != "research_gate"
        or findings.get("summary", {}).get("gate_result") != "pass"
        or findings.get("summary", {}).get("unresolved_blockers")
    ):
        raise CandidateAssemblyError(
            "findings must be an unblocked independent research_gate pass"
        )

    try:
        create_superseding_package(
            source,
            target,
            ledger_path=ledger_path,
            run_id=run_id,
            created_at=created_at,
            trusted_registry_path=trusted_registry_path,
        )
        for pattern in ("robustness_report.*", "findings.*"):
            for stale in target.glob(pattern):
                if stale.is_file():
                    stale.unlink()
        _write_json_atomic(target / "robustness_report.json", robustness)
        findings = {**findings, "package": "."}
        _write_json_atomic(target / "findings.json", findings)

        receipt_path = target / "run_receipt.json"
        receipt = _document(receipt_path, artifact_type="run_receipt")
        receipt["outputs"] = {
            **receipt.get("outputs", {}),
            "robustness_report": "robustness_report.json",
            "findings": "findings.json",
        }
        receipt["notes"] = (
            "Deterministically assembled research candidate; gate passage remains independent."
        )
        _write_json_atomic(receipt_path, receipt)

        metrics_path = target / "metrics_report.json"
        metrics = _document(metrics_path, artifact_type="metrics_report")
        metrics["sample"].update(
            {
                "evaluation_scope": "walk_forward",
                "holdout_start_time": robustness["validation"][
                    "holdout_start_time"
                ],
                "holdout_end_time": robustness["validation"]["holdout_end_time"],
            }
        )
        metrics["robustness"] = {
            "null_baseline_result": robustness["null_baseline"]["summary"],
            "dsr_or_psr": robustness["statistics"]["dsr"],
            "pbo": robustness["statistics"]["pbo"]["pbo"],
            "stress_results": [
                row["summary"] for row in robustness["stress_results"]
            ],
            "parameter_stability": robustness["parameter_stability"]["summary"],
        }
        _write_json_atomic(metrics_path, metrics)

        strategy_path = target / "strategy_spec.json"
        strategy = _document(strategy_path, artifact_type="strategy_spec")
        if strategy.get("status") == "draft":
            strategy["status"] = "research"
        _write_json_atomic(strategy_path, strategy)

        verdict_path = target / "verdict_report.json"
        verdict = _document(verdict_path, artifact_type="verdict_report")
        verdict.update(
            {
                "owner": findings["reviewer"],
                "verdict": "paper_candidate",
                "summary": (
                    "Measured run survived registered robustness checks and independent review."
                ),
                "next_action": "Evaluate the exact successor at research_gate.",
            }
        )
        verdict["gate_results"]["failed_gates"] = []
        verdict["evidence"] = {
            **verdict["evidence"],
            "robustness_report": "robustness_report.json",
        }
        _write_json_atomic(verdict_path, verdict)

        receipt = _document(receipt_path, artifact_type="run_receipt")
        receipt["candidate_assembly"] = candidate_assembly_manifest(
            strategy=strategy,
            metrics=metrics,
            verdict=verdict,
            robustness=robustness,
            findings=findings,
        )
        _write_json_atomic(receipt_path, receipt)

        validation = validate_package(target)
        if not validation.ok:
            details = "; ".join(
                f"{issue.path}: {issue.message}" for issue in validation.issues
            )
            raise CandidateAssemblyError(
                f"assembled candidate package is invalid: {details}"
            )
        target_id = build_run_entry(target, ledger_path=ledger_path)["package_id"]
        if target_id == source_entry["package_id"]:
            raise CandidateAssemblyError(
                "assembled candidate did not receive a new package identity"
            )
        return target, target_id
    except Exception:
        if target.exists():
            shutil.rmtree(target)
        raise

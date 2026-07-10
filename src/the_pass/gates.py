"""Artifact-backed promotion gate evaluation."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .ledger import (
    DEFAULT_LEDGER_PATH,
    artifact_identity_sha256,
    build_run_entry,
    collect_artifact_summaries,
    has_passed_gate,
    read_ledger_entries,
    verify_ledger_file,
)
from .validator import (
    find_artifact,
    load_document,
    parse_timestamp,
    validate_artifact,
    validate_package,
)


CORE_GATES = ("research_gate", "paper_gate", "risk_review", "live_gate")
DEFAULT_POLICY_PATH = (
    Path(__file__).resolve().parent / "policies" / "gate-policies.v1.yaml"
)


class GateEvaluationError(Exception):
    """Raised when gate evidence cannot be evaluated safely."""


@dataclass(frozen=True)
class GateEvaluation:
    decision: dict[str, Any]
    exit_code: int


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def policy_document(policy_path: Path) -> tuple[dict[str, Any], str]:
    policy_path = policy_path.resolve()
    try:
        raw = policy_path.read_bytes()
        document = yaml.safe_load(raw)
    except (OSError, yaml.YAMLError) as exc:
        raise GateEvaluationError(
            f"cannot load gate policy {policy_path}: {exc}"
        ) from exc
    if not isinstance(document, dict) or not isinstance(
        document.get("policy_version"), str
    ):
        raise GateEvaluationError("gate policy must contain policy_version")
    return document, hashlib.sha256(raw).hexdigest()


def workflow_artifact(
    package_dir: Path, artifact_type: str
) -> tuple[Path | None, dict[str, Any] | None, list[str]]:
    issues: list[str] = []
    path = next(
        (
            package_dir / f"{artifact_type}{extension}"
            for extension in (".json", ".yaml", ".yml")
            if (package_dir / f"{artifact_type}{extension}").is_file()
        ),
        None,
    )
    if path is None:
        return None, None, [f"missing {artifact_type} artifact"]
    validation = validate_artifact(path, artifact_type=artifact_type)
    if not validation.ok:
        issues.extend(
            f"{artifact_type}:{issue.path}: {issue.message}"
            for issue in validation.issues
        )
        return path, None, issues
    document = load_document(path)
    return path, document if isinstance(document, dict) else None, issues


def prior_gate_passes(ledger_path: Path, package_id: str, gate: str) -> bool:
    if not ledger_path.exists():
        return False
    if verify_ledger_file(ledger_path):
        return False
    return has_passed_gate(read_ledger_entries(ledger_path), package_id, gate)


def gate_audit_artifact(
    package_dir: Path,
    gate: str,
    reviewer: str,
    package_id: str,
) -> tuple[Path | None, list[str]]:
    matches = [
        package_dir / f"audit_report.{gate}{extension}"
        for extension in (".json", ".yaml", ".yml")
        if (package_dir / f"audit_report.{gate}{extension}").is_file()
    ]
    if not matches:
        return None, [f"missing independent audit_report.{gate} artifact"]
    if len(matches) > 1:
        return None, [f"ambiguous independent audit report for {gate}"]
    path = matches[0]
    validation = validate_artifact(path, artifact_type="audit_report")
    if not validation.ok:
        return path, [
            f"audit_report:{issue.path}: {issue.message}" for issue in validation.issues
        ]
    document = load_document(path)
    if not isinstance(document, dict):
        return path, ["independent audit report must be an object"]
    blockers: list[str] = []
    if document.get("target") != gate:
        blockers.append(f"independent audit report target must be {gate}")
    if document.get("reviewer") != reviewer:
        blockers.append(
            "gate reviewer must match the independent audit report reviewer"
        )
    if document.get("package_id") != package_id:
        blockers.append(
            "independent audit report package_id must match the exact package"
        )
    if document.get("verdict") != "pass":
        blockers.append("independent audit report is not a pass")
    if any(
        finding.get("blocks_promotion")
        and finding.get("status") in {"open", "confirmed"}
        for finding in document.get("findings", [])
        if isinstance(finding, dict)
    ):
        blockers.append(
            "independent audit report contains an unresolved blocking finding"
        )
    required_evidence = {
        "paper_gate": ("paper_plan", "observation_manifest", "divergence_report"),
        "risk_review": ("risk_report", "approval_pack", "config_diff"),
    }[gate]
    fingerprints = document.get("evidence_fingerprints")
    if not isinstance(fingerprints, list):
        blockers.append("independent audit report requires evidence fingerprints")
        return path, blockers
    fingerprint_rows = {
        item.get("path"): item.get("sha256")
        for item in fingerprints
        if isinstance(item, dict) and isinstance(item.get("path"), str)
    }
    if len(fingerprint_rows) != len(fingerprints):
        blockers.append(
            "independent audit report has duplicate or invalid evidence fingerprints"
        )
    for artifact_type in required_evidence:
        evidence_path = next(
            (
                package_dir / f"{artifact_type}{extension}"
                for extension in (".json", ".yaml", ".yml")
                if (package_dir / f"{artifact_type}{extension}").is_file()
            ),
            None,
        )
        expected_hash = (
            artifact_identity_sha256(artifact_type, evidence_path)
            if evidence_path is not None
            else None
        )
        evidence_name = (
            evidence_path.name if evidence_path is not None else artifact_type
        )
        if fingerprint_rows.get(evidence_name) != expected_hash:
            blockers.append(
                f"independent audit fingerprint does not match {evidence_name}"
            )
    return path, blockers


def reviewer_identity_blockers(package_dir: Path, reviewer: str) -> list[str]:
    blockers: list[str] = []
    owners: dict[str, str] = {}
    for artifact_type, label in (
        ("strategy_spec", "StrategySpec"),
        ("run_receipt", "run receipt"),
    ):
        path = find_artifact(package_dir, artifact_type)
        document = load_document(path) if path is not None else None
        owner = document.get("owner") if isinstance(document, dict) else None
        if not isinstance(owner, str) or not owner.strip():
            blockers.append(f"{label} owner is required for independent review")
        else:
            owners[label] = owner.strip()
    for label, owner in owners.items():
        if reviewer == owner:
            blockers.append(f"reviewer must differ from {label} owner")
    return blockers


def evaluate_gate(
    package_dir: Path,
    *,
    gate: str,
    reviewer: str,
    policy_path: Path = DEFAULT_POLICY_PATH,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
    trusted_entries: list[dict[str, Any]] | None = None,
) -> GateEvaluation:
    package_dir = package_dir.resolve()
    if gate not in CORE_GATES:
        raise GateEvaluationError(f"gate must be one of: {', '.join(CORE_GATES)}")
    if not reviewer.strip():
        raise GateEvaluationError("reviewer must be non-empty")

    package_validation = validate_package(package_dir)
    if not package_validation.ok:
        details = "; ".join(
            f"{issue.path}: {issue.message}" for issue in package_validation.issues
        )
        raise GateEvaluationError(f"package is invalid: {details}")

    policy, policy_hash = policy_document(policy_path)
    if gate not in policy.get("gates", {}):
        raise GateEvaluationError(f"gate policy does not define {gate}")

    run_entry = build_run_entry(package_dir)
    package_id = run_entry["package_id"]
    verdict_path, verdict, verdict_issues = workflow_artifact(
        package_dir, "verdict_report"
    )
    if verdict is None or verdict_path is None:
        raise GateEvaluationError("; ".join(verdict_issues) or "missing verdict report")

    blockers: list[str] = []
    result = "blocked"
    extra_evidence: list[dict[str, Any]] = []
    if gate != "live_gate":
        blockers.extend(reviewer_identity_blockers(package_dir, reviewer))

    if gate == "research_gate":
        _, findings, findings_issues = workflow_artifact(package_dir, "findings")
        if findings_issues:
            raise GateEvaluationError("; ".join(findings_issues))
        if findings is None or findings.get("reviewer") != reviewer:
            raise GateEvaluationError(
                "reviewer must match the package's independent findings reviewer"
            )
        verdict_state = verdict.get("verdict")
        if verdict_state == "paper_candidate" and not blockers:
            result = "pass"
        elif verdict_state in {"kill", "revise", "blocked"}:
            result = str(verdict_state)
            blockers.extend(run_entry.get("open_blockers", []))
            if not blockers:
                blockers.append(f"package verdict is {verdict_state}")
        else:
            blockers.append("package has no recognized research verdict")

    elif gate == "paper_gate":
        audit_path, audit_issues = gate_audit_artifact(
            package_dir, gate, reviewer, package_id
        )
        blockers.extend(audit_issues)
        if audit_path is not None:
            extra_evidence.append(
                {
                    "type": "audit_report",
                    "path": audit_path.name,
                    "sha256": hashlib.sha256(audit_path.read_bytes()).hexdigest(),
                }
            )
        if verdict.get("verdict") != "paper_candidate":
            blockers.append("paper_gate requires paper_candidate verdict")
        research_passes = (
            has_passed_gate(trusted_entries, package_id, "research_gate")
            if trusted_entries is not None
            else prior_gate_passes(ledger_path.resolve(), package_id, "research_gate")
        )
        if not research_passes:
            blockers.append("exact package has no passed research_gate decision")
        paper_path, paper_plan, paper_issues = workflow_artifact(
            package_dir, "paper_plan"
        )
        observation_path, observation, observation_issues = workflow_artifact(
            package_dir, "observation_manifest"
        )
        divergence_path, divergence, divergence_issues = workflow_artifact(
            package_dir, "divergence_report"
        )
        blockers.extend([*paper_issues, *observation_issues, *divergence_issues])
        for path, artifact_type in (
            (paper_path, "paper_plan"),
            (observation_path, "observation_manifest"),
            (divergence_path, "divergence_report"),
        ):
            if path is not None:
                extra_evidence.append(
                    {
                        "type": artifact_type,
                        "path": path.name,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    }
                )
        if paper_plan is not None and paper_plan.get("status") != "paper_ready":
            blockers.append("paper plan is not paper_ready")
        if divergence is not None:
            decision = divergence.get("decision", {})
            if decision.get("status") != "risk_review_candidate":
                blockers.append("divergence report is not risk_review_candidate")
            if any(
                item.get("blocks_promotion")
                for item in divergence.get("breaches", [])
                if isinstance(item, dict)
            ):
                blockers.append("divergence report contains a blocking breach")
        if paper_plan is not None and divergence is not None:
            sample = divergence.get("sample", {})
            minimum_days = paper_plan.get("observation", {}).get("minimum_days")
            minimum_signals = paper_plan.get("observation", {}).get("minimum_signals")
            start = parse_timestamp(sample.get("start_time"))
            end = parse_timestamp(sample.get("end_time"))
            if isinstance(minimum_days, int) and (
                start is None
                or end is None
                or end <= start
                or (end - start).total_seconds() < minimum_days * 86_400
            ):
                blockers.append("paper observation window is shorter than planned")
            if (
                isinstance(minimum_signals, int)
                and (sample.get("signals") or 0) < minimum_signals
            ):
                blockers.append("paper observation has fewer signals than planned")
        if not blockers:
            result = "pass"

    elif gate == "risk_review":
        audit_path, audit_issues = gate_audit_artifact(
            package_dir, gate, reviewer, package_id
        )
        blockers.extend(audit_issues)
        if audit_path is not None:
            extra_evidence.append(
                {
                    "type": "audit_report",
                    "path": audit_path.name,
                    "sha256": hashlib.sha256(audit_path.read_bytes()).hexdigest(),
                }
            )
        paper_passes = (
            has_passed_gate(trusted_entries, package_id, "paper_gate")
            if trusted_entries is not None
            else prior_gate_passes(ledger_path.resolve(), package_id, "paper_gate")
        )
        if not paper_passes:
            blockers.append("exact package has no passed paper_gate decision")
        risk_path, risk_report, risk_issues = workflow_artifact(
            package_dir, "risk_report"
        )
        approval_path, approval_pack, approval_issues = workflow_artifact(
            package_dir, "approval_pack"
        )
        config_path, config_diff, config_issues = workflow_artifact(
            package_dir, "config_diff"
        )
        blockers.extend([*risk_issues, *approval_issues, *config_issues])
        for path, artifact_type in (
            (risk_path, "risk_report"),
            (approval_path, "approval_pack"),
            (config_path, "config_diff"),
        ):
            if path is not None:
                extra_evidence.append(
                    {
                        "type": artifact_type,
                        "path": path.name,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    }
                )
        if risk_report is not None:
            if risk_report.get("package_id") != package_id:
                blockers.append(
                    "risk report package_id does not match the exact package"
                )
            if risk_report.get("verdict") != "pass" or risk_report.get("blockers"):
                blockers.append("risk report is not an unblocked pass")
        if approval_pack is not None:
            if approval_pack.get("requested_gate") != "risk_review":
                blockers.append("approval pack does not request risk_review")
            if approval_pack.get("status") != "packaged":
                blockers.append("approval pack is not packaged")
            if not approval_pack.get("evidence", {}).get("risk_reports"):
                blockers.append("approval pack does not reference a risk report")
        if approval_pack is not None and config_diff is not None:
            if approval_pack.get("config_hash") != config_diff.get("after_hash"):
                blockers.append(
                    "approval config_hash does not match config diff after_hash"
                )
        blockers.extend(run_entry.get("open_blockers", []))
        if not blockers:
            result = "pass"

    else:
        blockers.append(
            str(policy["gates"]["live_gate"].get("reason", "live gate is locked"))
        )

    evidence = [
        {key: value for key, value in item.items() if key != "identity_sha256"}
        for item in collect_artifact_summaries(package_dir)
    ]
    seen_paths = {item["path"] for item in evidence}
    evidence.extend(item for item in extra_evidence if item["path"] not in seen_paths)
    decision_id = f"gate_{gate}_{package_id[4:]}_{policy_hash[:8]}"
    decision = {
        "schema_version": 2,
        "id": decision_id,
        "created_at": utc_now_iso(),
        "gate_id": gate,
        "gate_result": result,
        "policy_version": policy["policy_version"],
        "policy_hash": policy_hash,
        "package_id": package_id,
        "package_path": ".",
        "reviewer": reviewer,
        "evidence": evidence,
        "blockers": blockers,
        "summary": "gate passed" if result == "pass" else "; ".join(blockers),
        "safety": {
            "grants_live_approval": False,
            "live_trading_enabled": False,
            "real_order_path_available": False,
        },
    }
    return GateEvaluation(
        decision, 0 if result == "pass" else (3 if gate == "live_gate" else 2)
    )


def write_gate_decision(path: Path, decision: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() == ".json":
        content = json.dumps(decision, indent=2, sort_keys=True) + "\n"
    elif path.suffix.lower() in {".yaml", ".yml"}:
        content = yaml.safe_dump(decision, sort_keys=False)
    else:
        raise GateEvaluationError("gate decision output must use .json, .yaml, or .yml")

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary_name, path)
        except FileExistsError as exc:
            raise GateEvaluationError(
                "gate decision already exists and cannot be overwritten or retried"
            ) from exc
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass

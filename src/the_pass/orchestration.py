"""Deterministic operational state for the slash-skill workflow."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from .ledger import (
    LEDGER_SCHEMA_V2,
    LedgerError,
    artifacts_hash,
    build_run_entry,
    has_passed_gate,
    read_ledger_entries,
    sha256_file,
    verify_ledger_file,
)
from .validator import (
    find_artifact,
    load_document,
    parse_timestamp,
    validate_artifact,
    validate_package,
)


DEFAULT_PIPELINE_PATH = (
    Path(__file__).resolve().parent / "policies" / "skill-pipeline.v1.yaml"
)
PUBLIC_SKILLS = ("run", "research", "test", "review", "paper", "plate", "status")
TERMINAL_STATUSES = {"killed", "complete"}
STAGE_PREREQUISITE_GATES = {
    "paper_prepare": ("research_gate",),
    "paper_observe": ("research_gate",),
    "review_paper": ("research_gate",),
    "paper_gate": ("research_gate",),
    "risk_prepare": ("research_gate", "paper_gate"),
    "plate": ("research_gate", "paper_gate"),
    "review_risk": ("research_gate", "paper_gate"),
    "risk_review": ("research_gate", "paper_gate"),
}
STAGES_REQUIRING_RECORDED_PACKAGE = {
    "robustness",
    "review_research",
    "research_gate",
    *STAGE_PREREQUISITE_GATES,
}
STAGE_REQUIRED_PACKAGE_EVIDENCE = {
    "research_gate": ("findings",),
    "paper_observe": ("paper_plan",),
    "review_paper": ("paper_plan", "observation_manifest", "divergence_report"),
    "paper_gate": (
        "paper_plan",
        "observation_manifest",
        "divergence_report",
        "audit_report.paper_gate",
    ),
    "plate": ("risk_policy", "risk_report"),
    "review_risk": ("risk_policy", "risk_report", "approval_pack", "config_diff"),
    "risk_review": (
        "risk_policy",
        "risk_report",
        "approval_pack",
        "config_diff",
        "audit_report.risk_review",
    ),
}


class WorkflowError(Exception):
    """Raised when operational workflow state is invalid."""


class ForbiddenWorkflowError(WorkflowError):
    """Raised when a workflow attempts to cross the public live boundary."""


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def load_pipeline_policy(path: Path = DEFAULT_PIPELINE_PATH) -> dict[str, Any]:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise WorkflowError(f"cannot load workflow policy {path}: {exc}") from exc
    if not isinstance(document, dict):
        raise WorkflowError("workflow policy must be an object")
    validate_pipeline_policy(document)
    return document


def validate_pipeline_policy(document: dict[str, Any]) -> None:
    if document.get("schema_version") != 1:
        raise WorkflowError("workflow policy schema_version must be 1")
    public_skills = document.get("public_skills")
    if not isinstance(public_skills, dict) or tuple(public_skills) != PUBLIC_SKILLS:
        raise WorkflowError(
            "workflow policy must define the seven public skills in canonical order"
        )
    if any(
        not isinstance(states, list)
        or not states
        or len(states) != len(set(states))
        or any(not isinstance(state, str) or not state for state in states)
        for states in public_skills.values()
    ):
        raise WorkflowError("every public skill must define exit states")

    runtime = document.get("runtime")
    if not isinstance(runtime, dict):
        raise WorkflowError("workflow policy requires runtime settings")
    if runtime.get("forbidden_target") != "live_gate" or "live_gate" in runtime.get(
        "target_gates", []
    ):
        raise WorkflowError("live_gate must remain a forbidden workflow target")
    for field in (
        "max_transitions",
        "max_remediation_laps",
        "max_consecutive_no_progress",
    ):
        if not isinstance(runtime.get(field), int) or runtime[field] <= 0:
            raise WorkflowError(f"runtime.{field} must be a positive integer")
    required_fields = runtime.get("required_state_fields")
    if not isinstance(required_fields, list) or len(required_fields) != len(
        set(required_fields)
    ):
        raise WorkflowError("runtime.required_state_fields must be a unique list")
    target_gates = runtime.get("target_gates")
    if (
        not isinstance(target_gates, list)
        or not target_gates
        or len(target_gates) != len(set(target_gates))
    ):
        raise WorkflowError("runtime.target_gates must be a unique non-empty list")
    statuses = runtime.get("statuses")
    if not isinstance(statuses, list) or set(statuses) != {
        "in_progress",
        "waiting",
        "blocked",
        "killed",
        "complete",
    }:
        raise WorkflowError(
            "runtime.statuses must define the canonical workflow states"
        )

    cli_contracts = document.get("cli_contracts")
    if not isinstance(cli_contracts, dict) or not cli_contracts:
        raise WorkflowError("workflow policy requires CLI contracts")
    for name, contract in cli_contracts.items():
        if not isinstance(contract, dict):
            raise WorkflowError(f"CLI contract {name} must be an object")
        if not isinstance(contract.get("argv"), list) or not contract["argv"]:
            raise WorkflowError(f"CLI contract {name} requires argv")
        if (
            not isinstance(contract.get("accepted_exit_codes"), list)
            or not contract["accepted_exit_codes"]
        ):
            raise WorkflowError(f"CLI contract {name} requires accepted_exit_codes")
        exit_codes = contract["accepted_exit_codes"]
        if len(exit_codes) != len(set(exit_codes)) or any(
            type(code) is not int or code not in range(4) for code in exit_codes
        ):
            raise WorkflowError(f"CLI contract {name} has invalid accepted_exit_codes")
        if not isinstance(contract.get("outputs"), list) or not contract["outputs"]:
            raise WorkflowError(f"CLI contract {name} requires outputs")
        if (
            not isinstance(contract.get("capability"), str)
            or not contract["capability"]
        ):
            raise WorkflowError(f"CLI contract {name} requires a capability predicate")

    stages = document.get("stages")
    if (
        not isinstance(stages, dict)
        or "preflight" not in stages
        or "complete" not in stages
    ):
        raise WorkflowError("workflow policy requires preflight and complete stages")
    stage_names = set(stages)
    for name, stage in stages.items():
        if not isinstance(stage, dict) or stage.get("skill") not in public_skills:
            raise WorkflowError(f"stage {name} must reference a public skill")
        contracts = stage.get("cli_contracts")
        if not isinstance(contracts, list) or any(
            contract not in cli_contracts for contract in contracts
        ):
            raise WorkflowError(f"stage {name} references an unknown CLI contract")
        transitions = stage.get("transitions")
        if (
            not isinstance(transitions, list)
            or len(transitions) != len(set(transitions))
            or any(target not in stage_names for target in transitions)
        ):
            raise WorkflowError(f"stage {name} has an unknown transition")
        if (
            stage.get("role") == "independent_reviewer"
            and stage.get("reviewer_required") is not True
        ):
            raise WorkflowError(
                f"independent review stage {name} must require a reviewer"
            )
    if stages["complete"].get("transitions") != []:
        raise WorkflowError("complete stage must be terminal")
    if any(target not in stage_names for target in runtime["target_gates"]):
        raise WorkflowError("every target gate must be a workflow stage")
    reachable = {"preflight"}
    pending = ["preflight"]
    while pending:
        current = pending.pop()
        for destination in stages[current]["transitions"]:
            if destination not in reachable:
                reachable.add(destination)
                pending.append(destination)
    if reachable != stage_names:
        raise WorkflowError(
            f"workflow has unreachable stages: {sorted(stage_names - reachable)}"
        )

    safety = document.get("safety")
    required_false = (
        "live_gate_target_allowed",
        "live_gate_pass_transition_allowed",
        "gate_decision_retryable",
        "real_order_transport_allowed",
        "credentials_allowed",
    )
    if not isinstance(safety, dict) or any(
        safety.get(field) is not False for field in required_false
    ):
        raise WorkflowError("workflow safety boundary is not fail-closed")
    if safety.get("paper_process_isolated") is not True:
        raise WorkflowError("paper process must remain isolated")


def new_workflow_state(
    *,
    run_id: str,
    objective: str,
    target_gate: str,
    strategy_owner: str,
    run_owner: str,
    ledger_path: Path,
    strategy_id: str = "pending",
    timestamp: str | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = policy or load_pipeline_policy()
    if target_gate == policy["runtime"]["forbidden_target"]:
        raise ForbiddenWorkflowError("live_gate is forbidden by the public workflow")
    if target_gate not in policy["runtime"]["target_gates"]:
        raise WorkflowError("target gate is not supported by the public workflow")
    if not all(
        value.strip() for value in (run_id, objective, strategy_owner, run_owner)
    ):
        raise WorkflowError(
            "run id, objective, strategy owner, and run owner are required"
        )
    now = timestamp or utc_now_iso()
    state = {
        "schema_version": 1,
        "run_id": run_id,
        "strategy_id": strategy_id or "pending",
        "objective": objective,
        "target_gate": target_gate,
        "strategy_owner": strategy_owner,
        "run_owner": run_owner,
        "reviewer": None,
        "started_at": now,
        "updated_at": now,
        "stage": "preflight",
        "status": "in_progress",
        "transitions_used": 0,
        "remediation_laps": 0,
        "no_progress_laps": 0,
        "package_path": None,
        "package_id": None,
        "ledger_path": str(ledger_path.resolve()),
        "evidence_paths": [],
        "blockers": [],
        "next_action": "run preflight",
    }
    validate_workflow_state(state, policy)
    return state


def validate_workflow_state(
    state: dict[str, Any], policy: dict[str, Any] | None = None
) -> None:
    policy = policy or load_pipeline_policy()
    required = set(policy["runtime"]["required_state_fields"])
    if set(state) != required:
        missing = sorted(required - set(state))
        extra = sorted(set(state) - required)
        raise WorkflowError(
            f"workflow state fields differ; missing={missing}, extra={extra}"
        )
    if state.get("schema_version") != 1:
        raise WorkflowError("workflow state schema_version must be 1")
    if state.get("target_gate") == policy["runtime"]["forbidden_target"]:
        raise ForbiddenWorkflowError("live_gate is forbidden by the public workflow")
    if state.get("target_gate") not in policy["runtime"]["target_gates"]:
        raise WorkflowError("workflow state has an unsupported target gate")
    if state.get("stage") not in policy["stages"]:
        raise WorkflowError("workflow state has an unknown stage")
    if state.get("status") not in policy["runtime"]["statuses"]:
        raise WorkflowError("workflow state has an unknown status")
    for field in (
        "run_id",
        "strategy_id",
        "objective",
        "strategy_owner",
        "run_owner",
        "ledger_path",
        "next_action",
    ):
        if not isinstance(state.get(field), str) or not state[field].strip():
            raise WorkflowError(f"workflow state requires {field}")
    reviewer = state.get("reviewer")
    if reviewer is not None and (not isinstance(reviewer, str) or not reviewer.strip()):
        raise WorkflowError("workflow reviewer must be null or a non-empty string")
    for field in ("transitions_used", "remediation_laps", "no_progress_laps"):
        if type(state.get(field)) is not int or state[field] < 0:
            raise WorkflowError(
                f"workflow state {field} must be a non-negative integer"
            )
    if state["transitions_used"] > policy["runtime"]["max_transitions"]:
        raise WorkflowError("workflow transition budget exceeded")
    if state["remediation_laps"] > policy["runtime"]["max_remediation_laps"]:
        raise WorkflowError("workflow remediation budget exceeded")
    if state["no_progress_laps"] > policy["runtime"]["max_consecutive_no_progress"]:
        raise WorkflowError("workflow no-progress counter exceeded")
    if not isinstance(state.get("evidence_paths"), list) or not all(
        isinstance(item, str) and item for item in state["evidence_paths"]
    ):
        raise WorkflowError("workflow evidence_paths must be a string list")
    if not isinstance(state.get("blockers"), list) or not all(
        isinstance(item, str) and item for item in state["blockers"]
    ):
        raise WorkflowError("workflow blockers must be a string list")
    if state["status"] in {"waiting", "blocked", "killed"} and not state["blockers"]:
        raise WorkflowError(
            f"workflow state {state['status']} requires at least one reason in blockers"
        )
    if (state["stage"] == "complete") != (state["status"] == "complete"):
        raise WorkflowError("complete stage and complete status must occur together")
    started_at = parse_timestamp(state.get("started_at"))
    updated_at = parse_timestamp(state.get("updated_at"))
    if started_at is None or updated_at is None or updated_at < started_at:
        raise WorkflowError("workflow timestamps must be ordered RFC3339 date-times")
    stage_contract = policy["stages"][state["stage"]]
    if stage_contract.get("reviewer_required") and (
        not isinstance(reviewer, str)
        or reviewer in {state["strategy_owner"], state["run_owner"]}
    ):
        raise WorkflowError(
            "independent review stage requires a reviewer distinct from both owners"
        )
    for field in ("package_path", "package_id"):
        if state.get(field) is not None and (
            not isinstance(state[field], str) or not state[field]
        ):
            raise WorkflowError(f"workflow {field} must be null or a non-empty string")
    if (state["package_path"] is None) != (state["package_id"] is None):
        raise WorkflowError("workflow package_path and package_id must be set together")


def verify_workflow_evidence(state: dict[str, Any]) -> None:
    ledger_path = Path(state["ledger_path"])
    stage = state["stage"]
    requires_recorded_package = (
        stage in STAGES_REQUIRING_RECORDED_PACKAGE or stage == "complete"
    )
    if requires_recorded_package and not ledger_path.exists():
        raise WorkflowError(f"workflow stage {stage} requires a verified ledger")
    entries: list[dict[str, Any]] = []
    if ledger_path.exists():
        issues = verify_ledger_file(ledger_path)
        if issues:
            details = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
            raise WorkflowError(f"workflow ledger verification failed: {details}")
        entries = read_ledger_entries(ledger_path)

    resolved_evidence = {Path(path).resolve() for path in state["evidence_paths"]}
    missing_evidence = [path for path in resolved_evidence if not path.exists()]
    if missing_evidence:
        raise WorkflowError(f"workflow evidence path is missing: {missing_evidence[0]}")

    if state["package_path"] is None:
        if requires_recorded_package:
            raise WorkflowError(f"workflow stage {stage} requires an exact package")
        return
    package_path = Path(state["package_path"])
    validation = validate_package(package_path)
    if not validation.ok:
        details = "; ".join(
            f"{issue.path}: {issue.message}" for issue in validation.issues
        )
        raise WorkflowError(f"workflow package verification failed: {details}")
    try:
        current_run_entry = build_run_entry(package_path, ledger_path=ledger_path)
        actual_package_id = current_run_entry["package_id"]
    except LedgerError as exc:
        raise WorkflowError(f"workflow package fingerprint failed: {exc}") from exc
    if actual_package_id != state["package_id"]:
        raise WorkflowError(
            "workflow package_id does not match current package evidence"
        )
    recorded_run = next(
        (
            entry
            for entry in entries
            if entry.get("schema") == LEDGER_SCHEMA_V2
            and entry.get("entry_kind") == "run"
            and entry.get("package_id") == state["package_id"]
            and (ledger_path.parent / str(entry.get("package_path", ""))).resolve()
            == package_path.resolve()
        ),
        None,
    )
    if requires_recorded_package and recorded_run is None:
        raise WorkflowError(
            f"workflow stage {stage} requires the exact package run in the ledger"
        )
    if recorded_run is not None and canonical_artifacts(
        recorded_run
    ) != canonical_artifacts(current_run_entry):
        raise WorkflowError(
            "workflow package artifacts differ from the recorded exact package"
        )

    for artifact_stem in STAGE_REQUIRED_PACKAGE_EVIDENCE.get(stage, ()):
        matches = [
            package_path / f"{artifact_stem}{extension}"
            for extension in (".json", ".yaml", ".yml")
            if (package_path / f"{artifact_stem}{extension}").is_file()
        ]
        if len(matches) != 1:
            raise WorkflowError(
                f"workflow stage {stage} requires one unambiguous {artifact_stem} artifact"
            )
        required_path = matches[0].resolve()
        if required_path not in resolved_evidence:
            raise WorkflowError(
                f"workflow stage {stage} must list {matches[0].name} in evidence_paths"
            )
    prerequisite_gates = (
        (state["target_gate"],)
        if stage == "complete"
        else STAGE_PREREQUISITE_GATES.get(stage, ())
    )
    for gate in prerequisite_gates:
        if not has_passed_gate(
            entries,
            state["package_id"],
            gate,
            ledger_path=ledger_path,
            package_path=package_path,
        ):
            raise WorkflowError(
                f"workflow stage {stage} requires exact-package {gate} passage"
            )


def canonical_artifacts(entry: dict[str, Any]) -> str:
    artifacts = entry.get("artifacts", [])
    return json.dumps(
        artifacts, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )


def workflow_target_passes(state: dict[str, Any]) -> bool:
    if state["package_id"] is None:
        return False
    ledger_path = Path(state["ledger_path"])
    if not ledger_path.exists() or verify_ledger_file(ledger_path):
        return False
    entries = read_ledger_entries(ledger_path)
    has_run = any(
        entry.get("schema") == LEDGER_SCHEMA_V2
        and entry.get("entry_kind") == "run"
        and entry.get("package_id") == state["package_id"]
        and (
            ledger_path.parent / str(entry.get("package_path", ""))
        ).resolve()
        == Path(str(state["package_path"])).resolve()
        for entry in entries
    )
    return has_run and has_passed_gate(
        entries,
        state["package_id"],
        state["target_gate"],
        ledger_path=ledger_path,
        package_path=Path(str(state["package_path"])),
    )


def _confirmed_finding_artifact(
    evidence_paths: list[str], *, expected_gate: str | None = None
) -> tuple[Path, str, dict[str, Any]]:
    issues: list[str] = []
    for value in evidence_paths:
        path = Path(value).resolve()
        for artifact_type in ("findings", "audit_report"):
            validation = validate_artifact(path, artifact_type=artifact_type)
            if not validation.ok:
                continue
            document = load_document(path)
            if not isinstance(document, dict):
                continue
            target = (
                document.get("target_gate")
                if artifact_type == "findings"
                else document.get("target")
            )
            if expected_gate is not None and target != expected_gate:
                issues.append(f"{path.name} targets {target}, not {expected_gate}")
                continue
            confirmed = [
                finding
                for finding in document.get("findings", [])
                if isinstance(finding, dict)
                and finding.get("status") == "confirmed"
                and finding.get("blocks_promotion") is True
            ]
            if confirmed:
                return path, artifact_type, document
            issues.append(f"{path.name} has no confirmed blocking finding")
    details = f": {'; '.join(issues)}" if issues else ""
    raise WorkflowError(
        "remediation requires a validated finding artifact with a confirmed blocking finding"
        + details
    )


def verify_target_remediation_entry(
    state: dict[str, Any], evidence_paths: list[str]
) -> None:
    package_value = state.get("package_path")
    package_id = state.get("package_id")
    if not isinstance(package_value, str) or not isinstance(package_id, str):
        raise WorkflowError("target remediation requires an exact recorded package")
    package_path = Path(package_value).resolve()
    finding_path, artifact_type, finding = _confirmed_finding_artifact(
        evidence_paths, expected_gate=state["target_gate"]
    )
    try:
        finding_relative = finding_path.relative_to(package_path).as_posix()
    except ValueError as exc:
        raise WorkflowError(
            "target remediation finding evidence must be inside the exact package"
        ) from exc

    ledger_path = Path(state["ledger_path"]).resolve()
    issues = verify_ledger_file(ledger_path)
    if issues:
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
        raise WorkflowError(f"target remediation requires a valid ledger: {details}")
    entries = read_ledger_entries(ledger_path)
    recorded_run = next(
        (
            entry
            for entry in entries
            if entry.get("schema") == LEDGER_SCHEMA_V2
            and entry.get("entry_kind") == "run"
            and entry.get("package_id") == package_id
            and (ledger_path.parent / str(entry.get("package_path", ""))).resolve()
            == package_path
        ),
        None,
    )
    if recorded_run is None:
        raise WorkflowError("target remediation package is not the exact recorded run")
    decision = next(
        (
            entry
            for entry in reversed(entries)
            if entry.get("schema") == LEDGER_SCHEMA_V2
            and entry.get("entry_kind") == "gate_decision"
            and entry.get("package_id") == package_id
            and entry.get("gate") == state["target_gate"]
            and entry.get("gate_result") in {"blocked", "revise"}
            and (ledger_path.parent / str(entry.get("package_path", ""))).resolve()
            == package_path
        ),
        None,
    )
    if decision is None:
        raise WorkflowError(
            "target remediation requires a recorded blocked or revise gate decision"
        )
    evidence = [
        item
        for item in decision.get("artifacts", [])
        if isinstance(item, dict)
        and item.get("type") == artifact_type
        and item.get("path") == finding_relative
    ]
    if len(evidence) != 1 or evidence[0].get("sha256") != sha256_file(finding_path):
        raise WorkflowError(
            "target remediation finding is not fingerprinted by the non-pass gate decision"
        )
    if finding.get("reviewer") != decision.get("reviewer"):
        raise WorkflowError(
            "target remediation finding reviewer does not match the gate decision"
        )
    if artifact_type == "findings" and finding.get("package") not in {".", package_id}:
        raise WorkflowError("target remediation findings do not bind the exact package")
    if artifact_type == "audit_report" and finding.get("package_id") != package_id:
        raise WorkflowError("target remediation audit does not bind the exact package")


def verify_remediation_progress(
    state: dict[str, Any], package_path: str | None, package_id: str | None
) -> None:
    if package_path is None or package_id is None:
        raise WorkflowError(
            "moved_gate requires a new recorded successor package and package_id"
        )
    predecessor_id = state.get("package_id")
    if not isinstance(predecessor_id, str) or package_id == predecessor_id:
        raise WorkflowError("moved_gate requires a different successor package")
    ledger_path = Path(state["ledger_path"]).resolve()
    issues = verify_ledger_file(ledger_path)
    if issues:
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
        raise WorkflowError(f"moved_gate requires a valid ledger: {details}")
    expected_path = Path(package_path).resolve()
    successor = next(
        (
            entry
            for entry in read_ledger_entries(ledger_path)
            if entry.get("schema") == LEDGER_SCHEMA_V2
            and entry.get("entry_kind") == "run"
            and entry.get("package_id") == package_id
            and (ledger_path.parent / str(entry.get("package_path", ""))).resolve()
            == expected_path
        ),
        None,
    )
    if successor is None or successor.get("supersedes_package_id") != predecessor_id:
        raise WorkflowError(
            "moved_gate successor is not a recorded child of the current package"
        )


def read_workflow_state(
    path: Path,
    policy: dict[str, Any] | None = None,
    *,
    verify_evidence: bool = True,
) -> dict[str, Any]:
    try:
        state = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise WorkflowError(f"cannot read workflow state {path}: {exc}") from exc
    if not isinstance(state, dict):
        raise WorkflowError("workflow state must be an object")
    validate_workflow_state(state, policy)
    if verify_evidence:
        verify_workflow_evidence(state)
    return state


def write_workflow_state_atomic(
    path: Path, state: dict[str, Any], policy: dict[str, Any] | None = None
) -> None:
    validate_workflow_state(state, policy)
    verify_workflow_evidence(state)
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            yaml.safe_dump(state, handle, sort_keys=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def advance_workflow_state(
    state: dict[str, Any],
    *,
    to_stage: str | None,
    status: str,
    next_action: str,
    reviewer: str | None = None,
    evidence_paths: list[str] | None = None,
    blockers: list[str] | None = None,
    package_path: str | None = None,
    package_id: str | None = None,
    remediation: bool = False,
    moved_gate: bool = False,
    resume: bool = False,
    timestamp: str | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = policy or load_pipeline_policy()
    validate_workflow_state(state, policy)
    if state["status"] in TERMINAL_STATUSES:
        raise WorkflowError(f"cannot advance terminal workflow state {state['status']}")
    if state["status"] == "blocked" and not resume:
        raise WorkflowError(
            "blocked workflow requires an explicit resume after its blocker is resolved"
        )
    if state["status"] == "blocked" and resume and (
        state["transitions_used"] >= policy["runtime"]["max_transitions"]
        or state["remediation_laps"] >= policy["runtime"]["max_remediation_laps"]
        or state["no_progress_laps"]
        >= policy["runtime"]["max_consecutive_no_progress"]
    ):
        raise WorkflowError(
            "exhausted workflow budgets are non-resumable; start a new bounded run"
        )
    if status not in policy["runtime"]["statuses"]:
        raise WorkflowError("unknown workflow status")
    if not next_action.strip():
        raise WorkflowError("next_action is required")

    current_stage = state["stage"]
    destination = to_stage or current_stage
    entering_remediation = current_stage != "remediation" and destination == "remediation"
    remediation_attempt = remediation or (
        destination == "remediation" and status == "in_progress"
    )
    if remediation and current_stage != "remediation" and destination != "remediation":
        raise WorkflowError(
            "remediation accounting is only valid when entering, running, or leaving remediation"
        )
    if entering_remediation:
        if status != "in_progress":
            raise WorkflowError("workflow may enter remediation only in_progress")
        if not evidence_paths:
            raise WorkflowError(
                "entering remediation requires evidence paths for confirmed findings"
            )
        if current_stage == state["target_gate"]:
            verify_target_remediation_entry(state, evidence_paths)
        else:
            _confirmed_finding_artifact(evidence_paths)
    if moved_gate and not remediation_attempt:
        raise WorkflowError("moved_gate is valid only for a remediation attempt")
    if remediation_attempt and moved_gate:
        verify_remediation_progress(state, package_path, package_id)
    if (
        destination != current_stage
        and destination not in policy["stages"][current_stage]["transitions"]
    ):
        raise WorkflowError(
            f"illegal workflow transition: {current_stage} -> {destination}"
        )
    if status == "complete" and destination != "complete":
        raise WorkflowError("complete status requires transition to complete stage")
    if destination == "complete" and status != "complete":
        raise WorkflowError("complete stage requires complete status")
    target_gate = state["target_gate"]
    if current_stage == target_gate:
        target_passed = workflow_target_passes(state)
        allowed_failed_target_transition = (
            (destination == current_stage and status in {"blocked", "killed"})
            or (destination == current_stage and status == "in_progress" and resume)
            or (destination == "remediation" and status == "in_progress")
        )
        if target_passed and destination != "complete":
            raise WorkflowError(
                f"passed workflow target {target_gate} must terminate at complete"
            )
        if (
            not target_passed
            and destination != "complete"
            and not allowed_failed_target_transition
        ):
            raise WorkflowError(
                f"failed workflow target {target_gate} must block, kill, resume, or enter remediation"
            )
    if destination == "complete" and current_stage != target_gate:
        raise WorkflowError(
            f"workflow cannot complete before target gate {target_gate}"
        )
    if destination == "complete" and not workflow_target_passes(state):
        raise WorkflowError(
            "workflow cannot complete without a verified exact-package target gate pass"
        )

    updated = dict(state)
    # Finalizing a verified target is terminal bookkeeping, not another work step.
    # Reserving it outside the transition budget prevents a passed gate from being
    # rewritten as blocked at the exact budget boundary.
    consumes_transition = destination != "complete"
    if (
        consumes_transition
        and updated["transitions_used"] >= policy["runtime"]["max_transitions"]
    ):
        updated["status"] = "blocked"
        updated["blockers"] = ["workflow transition budget exhausted"]
        updated["next_action"] = "review workflow scope and start a new bounded run"
        updated["updated_at"] = timestamp or utc_now_iso()
        validate_workflow_state(updated, policy)
        return updated
    if consumes_transition:
        updated["transitions_used"] += 1

    if remediation_attempt:
        if updated["remediation_laps"] >= policy["runtime"]["max_remediation_laps"]:
            updated["status"] = "blocked"
            updated["blockers"] = ["workflow remediation budget exhausted"]
            updated["next_action"] = (
                "independent review must redefine the remediation scope"
            )
            updated["updated_at"] = timestamp or utc_now_iso()
            validate_workflow_state(updated, policy)
            return updated
        updated["remediation_laps"] += 1
        updated["no_progress_laps"] = (
            0 if moved_gate else updated["no_progress_laps"] + 1
        )
        if (
            updated["no_progress_laps"]
            >= policy["runtime"]["max_consecutive_no_progress"]
        ):
            updated["status"] = "blocked"
            updated["blockers"] = [
                "two consecutive remediation laps made no gate progress"
            ]
            updated["next_action"] = "block or kill instead of continuing the loop"
            updated["updated_at"] = timestamp or utc_now_iso()
            validate_workflow_state(updated, policy)
            return updated

    destination_contract = policy["stages"][destination]
    if destination_contract.get("reviewer_required"):
        owners = {state["strategy_owner"], state["run_owner"]}
        effective_reviewer = reviewer if reviewer is not None else state.get("reviewer")
        if not effective_reviewer or effective_reviewer in owners:
            updated["status"] = "blocked"
            updated["reviewer"] = effective_reviewer
            updated["blockers"] = [
                "independent reviewer must be present and differ from strategy and run owners"
            ]
            updated["next_action"] = (
                "invoke /the-pass:review in an independent review context"
            )
            updated["updated_at"] = timestamp or utc_now_iso()
            validate_workflow_state(updated, policy)
            return updated
        updated["reviewer"] = effective_reviewer
    elif reviewer is not None:
        updated["reviewer"] = reviewer

    updated["stage"] = destination
    updated["status"] = status
    updated["updated_at"] = timestamp or utc_now_iso()
    updated["next_action"] = next_action
    updated["blockers"] = list(blockers or [])
    new_evidence = [str(Path(path).resolve()) for path in (evidence_paths or [])]
    if any(not Path(path).exists() for path in new_evidence):
        raise WorkflowError(
            "workflow evidence paths must exist before they are recorded"
        )
    updated["evidence_paths"] = list(
        dict.fromkeys([*state["evidence_paths"], *new_evidence])
    )
    if (package_path is None) != (package_id is None):
        raise WorkflowError("package_path and package_id must be updated together")
    if package_path is not None and package_id is not None:
        updated["package_path"] = str(Path(package_path).resolve())
        updated["package_id"] = package_id
    validate_workflow_state(updated, policy)
    verify_workflow_evidence(updated)
    return updated


def _write_document_atomic(path: Path, document: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            if path.suffix.lower() == ".json":
                json.dump(document, handle, indent=2, sort_keys=True)
                handle.write("\n")
            else:
                yaml.safe_dump(document, handle, sort_keys=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def create_superseding_package(
    source: Path,
    target: Path,
    *,
    ledger_path: Path,
    run_id: str,
    created_at: str,
    trusted_registry_path: Path | None = None,
) -> tuple[Path, str]:
    source = source.resolve()
    target = target.resolve()
    ledger_path = ledger_path.resolve()
    try:
        target.relative_to(source)
    except ValueError:
        pass
    else:
        raise WorkflowError(
            "superseding package target must be outside the source package"
        )
    if any(path.is_symlink() for path in source.rglob("*")):
        raise WorkflowError(
            "superseding package source must not contain symbolic links"
        )
    validation = validate_package(source)
    if not validation.ok:
        details = "; ".join(
            f"{issue.path}: {issue.message}" for issue in validation.issues
        )
        raise WorkflowError(f"cannot supersede invalid package: {details}")
    if target.exists():
        raise WorkflowError("superseding package target must not exist")
    if not run_id.strip():
        raise WorkflowError("superseding package requires a new run id")

    if not ledger_path.is_file():
        raise WorkflowError("superseding package requires an existing source ledger")
    ledger_issues = verify_ledger_file(
        ledger_path, trusted_registry_path=trusted_registry_path
    )
    if ledger_issues:
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in ledger_issues)
        raise WorkflowError(f"cannot supersede from an invalid ledger: {details}")
    try:
        source_entry = build_run_entry(source, ledger_path=ledger_path)
    except LedgerError as exc:
        raise WorkflowError(f"cannot fingerprint source package: {exc}") from exc
    recorded_source = next(
        (
            entry
            for entry in read_ledger_entries(ledger_path)
            if entry.get("schema") == LEDGER_SCHEMA_V2
            and entry.get("entry_kind") == "run"
            and entry.get("package_id") == source_entry["package_id"]
        ),
        None,
    )
    if recorded_source is None:
        raise WorkflowError("superseding package source is not recorded in the ledger")
    recorded_path = (
        ledger_path.parent / str(recorded_source.get("package_path", ""))
    ).resolve()
    if recorded_path != source:
        raise WorkflowError(
            "superseding package source path does not match its ledger receipt"
        )
    if canonical_artifacts(recorded_source) != canonical_artifacts(source_entry):
        raise WorkflowError(
            "superseding package source differs from its recorded ledger evidence"
        )
    if run_id == source_entry["run_id"]:
        raise WorkflowError(
            "superseding package requires a run id different from the source"
        )
    source_artifacts_hash = artifacts_hash(source_entry)
    try:
        shutil.copytree(source, target)
        for stale in target.glob("gate_decision*"):
            if stale.is_file():
                stale.unlink()
        for ledger_name in ("receipt-ledger.jsonl", "ledger.jsonl"):
            ledger_path = target / ledger_name
            if ledger_path.is_file():
                ledger_path.unlink()

        receipt_path = find_artifact(target, "run_receipt")
        if receipt_path is None:
            raise WorkflowError("copied package has no run receipt")
        receipt = load_document(receipt_path)
        if not isinstance(receipt, dict):
            raise WorkflowError("run receipt must be an object")
        receipt.update(
            {
                "id": run_id,
                "created_at": created_at,
                "supersedes_package_id": source_entry["package_id"],
                "supersedes_artifacts_hash": source_artifacts_hash,
            }
        )
        _write_document_atomic(receipt_path, receipt)
        target_validation = validate_package(target)
        if not target_validation.ok:
            details = "; ".join(
                f"{issue.path}: {issue.message}" for issue in target_validation.issues
            )
            raise WorkflowError(f"superseding package failed validation: {details}")
        try:
            target_id = build_run_entry(target)["package_id"]
        except LedgerError as exc:
            raise WorkflowError(
                f"cannot fingerprint superseding package: {exc}"
            ) from exc
        if target_id == source_entry["package_id"]:
            raise WorkflowError("superseding package must receive a new package id")
        return target, target_id
    except Exception:
        if target.exists():
            shutil.rmtree(target)
        raise

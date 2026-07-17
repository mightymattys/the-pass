"""CLI command handlers."""

# ruff: noqa: F401
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

import yaml

from .. import __version__
from ..automation import run_automation_spec
from ..candidate import CandidateAssemblyError, assemble_research_candidate
from ..audit import ReproductionError, reproduce_package
from ..attestation import (
    ATTESTABLE_GATES,
    AttestationError,
    create_reviewer_key_registry,
    create_reviewer_attestation,
    generate_reviewer_keypair,
    registry_snapshot_path,
    review_task_path,
    write_private_signing_key,
    write_registry_snapshot,
    write_reviewer_attestation,
)
from ..agent_orchestration import (
    AgentOrchestrationError,
    AgentSafetyError,
    dispatch_agent_task,
    doctor_agents,
    inspect_agent_task,
    model_catalog_status,
    route_workflow_stage,
)
from ..data.contracts import CanonicalEvent
from ..adapters.base import FetchRequest
from ..data.dataset import build_dataset, build_dataset_plan, validate_dataset_plan
from ..data.features import build_bar_features
from ..data.ingest import ingest_bundle
from ..data.quality import QualityPolicy, build_quality_report
from ..engine.package import preregister_search_space, write_run_package
from ..engine.screen import ReferenceScreenRunner
from ..engine.workflows import BASELINE_NAMES, run_baseline
from ..incident import build_incident_report
from ..paper import (
    ObservationPolicy,
    PaperObservationError,
    observe_strategy,
    run_virtual_paper_process,
)
from ..reporting import build_static_dashboard
from ..research_evidence import build_research_evidence_report
from ..risk import build_risk_policy_artifact, build_risk_report
from ..robustness import (
    cscv_pbo,
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
    reality_check,
    run_strategy_sweep,
)
from ..strategy_runtime import (
    StrategyRuntimeError,
    run_strategy_verified,
    runner_result_from_document,
)
from ..ledger import (
    DEFAULT_LEDGER_PATH,
    LedgerError,
    append_ledger_entry,
    append_gate_decision,
    build_run_entry,
    format_ledger_summary,
    ledger_summary,
    read_ledger_entries,
    verify_ledger_file,
)
from ..gates import (
    CORE_GATES,
    DEFAULT_POLICY_PATH,
    GateEvaluationError,
    evaluate_gate,
    write_gate_decision,
)
from ..orchestration import (
    ForbiddenWorkflowError,
    WorkflowError,
    advance_workflow_state,
    create_superseding_package,
    new_workflow_state,
    read_workflow_state,
    write_workflow_state_atomic,
)
from ..workflow_supervisor import (
    WorkflowSupervisorError,
    inspect_workflow_execution,
    supervise_workflow,
)
from ..validator import (
    ARTIFACT_TYPES,
    ValidationResult,
    validate_artifact,
    validate_package,
    load_document,
    repo_root_from,
)


from .._infra import write_json_atomic
from ..cli import build_read_only_adapter, load_event_jsonl, load_fetch_request, print_envelope, print_result

def handle_incident(args: argparse.Namespace) -> int:
    try:
        document = build_incident_report(
            incident_id=args.id,
            severity=args.severity,
            detected_at=args.detected_at,
            source=args.source,
            summary=args.summary,
            evidence=args.evidence,
            freeze_reason=args.freeze_reason,
        )
        write_json_atomic(args.output, document)
        validation = validate_artifact(args.output, artifact_type="incident_report")
        if not validation.ok:
            raise ValueError("generated incident report does not validate")
        print_envelope(
            output_format=args.format,
            ok=True,
            status="contained",
            artifact_paths=[args.output.resolve()],
        )
        return 0
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        print_envelope(
            output_format=args.format,
            ok=False,
            status="error",
            issues=[{"path": str(args.output), "message": str(exc)}],
        )
        return 1


def handle_workflow(args: argparse.Namespace) -> int:
    try:
        if args.workflow_command == "start":
            if args.state.exists():
                raise WorkflowError(
                    "workflow state already exists; use workflow status or advance"
                )
            state = new_workflow_state(
                run_id=args.run_id,
                strategy_id=args.strategy_id,
                objective=args.objective,
                target_gate=args.target_gate,
                strategy_owner=args.strategy_owner,
                run_owner=args.run_owner,
                ledger_path=args.ledger,
                timestamp=args.started_at,
            )
            write_workflow_state_atomic(args.state, state)
            print_envelope(
                output_format=args.format,
                ok=True,
                status="in_progress",
                artifact_paths=[args.state.resolve()],
                details={"workflow": state},
            )
            return 0

        if args.workflow_command == "advance":
            state = read_workflow_state(args.state)
            state = advance_workflow_state(
                state,
                to_stage=args.to_stage,
                status=args.status,
                next_action=args.next_action,
                reviewer=args.reviewer,
                evidence_paths=args.evidence,
                blockers=args.blocker,
                package_path=args.package_path,
                package_id=args.package_id,
                remediation=args.remediation,
                moved_gate=args.moved_gate == "true",
                resume=args.resume,
                timestamp=args.updated_at,
            )
            write_workflow_state_atomic(args.state, state)
            non_promoted = state["status"] in {"waiting", "blocked", "killed"}
            print_envelope(
                output_format=args.format,
                ok=not non_promoted,
                status=state["status"],
                artifact_paths=[args.state.resolve()],
                issues=[
                    {"path": str(args.state), "message": blocker}
                    for blocker in state["blockers"]
                ],
                details={"workflow": state},
            )
            return 2 if non_promoted else 0

        if args.workflow_command == "status":
            state = read_workflow_state(args.state)
            print_envelope(
                output_format=args.format,
                ok=True,
                status=state["status"],
                artifact_paths=[args.state.resolve()],
                details={"workflow": state},
            )
            return 0

        if args.workflow_command == "execute":
            providers = args.available_providers or ("codex", "claude")
            report_path = args.report or args.state.parent / "supervisor-run.json"
            if not args.driver:
                raise WorkflowSupervisorError(
                    "workflow execute requires a command after --driver"
                )
            if not args.execute:
                inspection = inspect_workflow_execution(
                    args.state,
                    driver_argv=args.driver,
                    author_provider=args.author_provider,
                    available_providers=providers,
                )
                print_envelope(
                    output_format=args.format,
                    ok=True,
                    status="inspection",
                    artifact_paths=[args.state.resolve()],
                    details={"inspection": inspection},
                )
                return 0
            report, exit_code = supervise_workflow(
                args.state,
                driver_argv=args.driver,
                cwd=args.cwd,
                report_path=report_path,
                author_provider=args.author_provider,
                available_providers=providers,
                max_cycles=args.max_cycles,
                timeout_seconds=args.timeout_seconds,
                max_output_bytes=args.max_output_bytes,
            )
            print_envelope(
                output_format=args.format,
                ok=exit_code == 0,
                status=report["status"],
                artifact_paths=[args.state.resolve(), report_path.resolve()],
                issues=[
                    {"path": str(report_path), "message": issue}
                    for issue in report["issues"]
                ],
                details={"supervisor": report},
            )
            return exit_code

        if args.workflow_command == "fingerprint":
            package_id = build_run_entry(args.package)["package_id"]
            print_envelope(
                output_format=args.format,
                ok=True,
                status="complete",
                artifact_paths=[args.package.resolve()],
                receipt_id=package_id,
                details={"package_id": package_id},
            )
            return 0

        target, package_id = create_superseding_package(
            args.source,
            args.target,
            ledger_path=args.ledger,
            run_id=args.run_id,
            created_at=args.created_at,
            trusted_registry_path=args.trusted_reviewers,
        )
        print_envelope(
            output_format=args.format,
            ok=True,
            status="complete",
            artifact_paths=[target],
            receipt_id=package_id,
            details={"package_id": package_id},
        )
        return 0
    except ForbiddenWorkflowError as exc:
        print_envelope(
            output_format=args.format,
            ok=False,
            status="forbidden",
            issues=[
                {
                    "path": str(getattr(args, "state", "workflow")),
                    "message": str(exc),
                }
            ],
        )
        return 3
    except (LedgerError, OSError, WorkflowError) as exc:
        print_envelope(
            output_format=args.format,
            ok=False,
            status="error",
            issues=[
                {
                    "path": str(getattr(args, "state", "workflow")),
                    "message": str(exc),
                }
            ],
        )
        return 1


def handle_gate(args: argparse.Namespace) -> int:
    try:
        if args.gate_command == "keygen":
            private_key, public_key = generate_reviewer_keypair()
            registry = create_reviewer_key_registry(
                registry_id=args.registry_id,
                reviewer=args.reviewer,
                principal_type=args.principal_type,
                provider=args.provider,
                public_key=public_key,
                created_at=args.created_at,
                valid_from=args.valid_from,
                valid_until=args.valid_until,
            )
            write_private_signing_key(args.private_key_output, private_key)
            try:
                write_registry_snapshot(args.registry_output, registry)
            except Exception:
                args.private_key_output.unlink(missing_ok=True)
                raise
            print_envelope(
                output_format=args.format,
                ok=True,
                status="complete",
                artifact_paths=[args.private_key_output, args.registry_output],
                details={
                    "registry_id": registry["id"],
                    "key_id": registry["keys"][0]["key_id"],
                },
            )
            return 0
        package_dir = args.package.resolve()
        output_path = args.output.resolve()
        if output_path.parent != package_dir:
            raise GateEvaluationError(
                "gate output must be stored in the package directory"
            )
        if args.gate_command == "attest":
            if output_path.name != f"reviewer_attestation.{args.gate}.json":
                raise AttestationError(
                    f"attestation output must be named reviewer_attestation.{args.gate}.json"
                )
            expected_task = review_task_path(package_dir, args.gate)
            if args.task_evidence.resolve() != expected_task:
                raise AttestationError(
                    "task evidence must be the exact gate findings or audit report"
                )
            empty_hash = hashlib.sha256(b"").hexdigest()
            evidence = {
                "state_before_sha256": hashlib.sha256(
                    args.state_before.read_bytes()
                ).hexdigest(),
                "state_after_sha256": hashlib.sha256(
                    args.state_after.read_bytes()
                ).hexdigest(),
                "task_sha256": hashlib.sha256(
                    args.task_evidence.read_bytes()
                ).hexdigest(),
                "stdout_sha256": hashlib.sha256(
                    args.stdout_evidence.read_bytes()
                ).hexdigest()
                if args.stdout_evidence
                else empty_hash,
                "stderr_sha256": hashlib.sha256(
                    args.stderr_evidence.read_bytes()
                ).hexdigest()
                if args.stderr_evidence
                else empty_hash,
            }
            operator_ledger = (
                args.ledger.resolve()
                if args.ledger.is_absolute()
                else (repo_root_from(Path(__file__)) / args.ledger).resolve()
            )
            package_id = build_run_entry(
                package_dir, ledger_path=operator_ledger
            )["package_id"]
            registry_validation = validate_artifact(
                args.key_registry, artifact_type="reviewer_key_registry"
            )
            if not registry_validation.ok:
                details = "; ".join(
                    f"{issue.path}: {issue.message}"
                    for issue in registry_validation.issues
                )
                raise AttestationError(f"invalid reviewer key registry: {details}")
            registry = load_document(args.key_registry)
            if not isinstance(registry, dict):
                raise AttestationError("reviewer key registry must be an object")
            attestation = create_reviewer_attestation(
                gate=args.gate,
                package_id=package_id,
                reviewer=args.reviewer,
                principal_type=args.principal_type,
                provider=args.provider,
                model=args.model,
                run_id=args.run_id,
                author_provider=args.author_provider,
                reviewer_provider=args.reviewer_provider,
                evidence=evidence,
                registry=registry,
                created_at=args.created_at,
            )
            snapshot = registry_snapshot_path(package_dir, args.gate)
            write_registry_snapshot(snapshot, registry)
            write_reviewer_attestation(output_path, attestation)
            print_envelope(
                output_format=args.format,
                ok=True,
                status="complete",
                artifact_paths=[snapshot, output_path],
                details={"attestation": attestation},
            )
            return 0
        if output_path.stem != f"gate_decision.{args.gate}":
            raise GateEvaluationError(
                f"gate decision output must be named gate_decision.{args.gate}.json|yaml|yml"
            )
        evaluation = evaluate_gate(
            package_dir,
            gate=args.gate,
            reviewer=args.reviewer,
            policy_path=args.policy,
            ledger_path=args.ledger,
            trusted_registry_path=args.trusted_reviewers,
        )
        write_gate_decision(output_path, evaluation.decision)
        if args.format == "json":
            print(
                json.dumps(
                    {
                        "ok": evaluation.exit_code == 0,
                        "status": evaluation.decision["gate_result"],
                        "artifact_paths": [str(output_path)],
                        "issues": [],
                        "receipt_id": None,
                        "decision": evaluation.decision,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(
                f"{args.gate}: {evaluation.decision['gate_result']} -> {output_path}"
            )
            for blocker in evaluation.decision["blockers"]:
                print(f"- {blocker}")
        return evaluation.exit_code
    except (AttestationError, GateEvaluationError, OSError) as exc:
        if args.format == "json":
            print(
                json.dumps(
                    {
                        "ok": False,
                        "status": "error",
                        "artifact_paths": [],
                        "issues": [
                            {"path": str(args.package), "message": str(exc)}
                        ],
                        "receipt_id": None,
                    }
                )
            )
        else:
            print(f"gate evaluation error: {exc}", file=sys.stderr)
        return 1


def handle_receipts(args: argparse.Namespace) -> int:
    ledger_path = getattr(args, "sub_ledger", None) or args.ledger
    try:
        if args.receipts_command == "add":
            append_result = append_ledger_entry(
                ledger_path,
                args.package,
                trusted_registry_path=args.trusted_reviewers,
            )
            if args.format == "json":
                print_envelope(
                    output_format=args.format,
                    ok=True,
                    status="appended" if append_result.appended else "duplicate",
                    artifact_paths=[ledger_path.resolve()],
                    receipt_id=append_result.entry["package_id"],
                    details={
                        "entry": append_result.entry,
                        "message": append_result.message,
                    },
                )
            else:
                print(
                    f"{append_result.message}: {append_result.entry['package_id']}"
                )
            return 0

        if args.receipts_command == "add-decision":
            append_result = append_gate_decision(
                ledger_path,
                args.decision,
                trusted_registry_path=args.trusted_reviewers,
            )
            if args.format == "json":
                print_envelope(
                    output_format=args.format,
                    ok=True,
                    status="appended" if append_result.appended else "duplicate",
                    artifact_paths=[ledger_path.resolve()],
                    receipt_id=append_result.entry["decision_id"],
                    details={
                        "entry": append_result.entry,
                        "message": append_result.message,
                    },
                )
            else:
                print(
                    f"{append_result.message}: {append_result.entry['decision_id']}"
                )
            return 0

        if args.receipts_command == "verify":
            issues = verify_ledger_file(
                ledger_path,
                trusted_registry_path=args.trusted_reviewers,
            )
            if args.format == "json":
                print_envelope(
                    output_format=args.format,
                    ok=not issues,
                    status="verified" if not issues else "invalid",
                    artifact_paths=[ledger_path.resolve()]
                    if ledger_path.exists()
                    else [],
                    issues=[issue.as_dict() for issue in issues],
                )
            elif issues:
                print("ledger verification failed", file=sys.stderr)
                for issue in issues:
                    print(f"- {issue.path}: {issue.message}", file=sys.stderr)
            else:
                print(f"{ledger_path} ledger verifies")
            return 0 if not issues else 1

        entries = read_ledger_entries(ledger_path)
        issues = verify_ledger_file(ledger_path) if ledger_path.exists() else []
        if issues:
            if args.format == "json":
                print_envelope(
                    output_format=args.format,
                    ok=False,
                    status="invalid",
                    artifact_paths=[ledger_path.resolve()],
                    issues=[issue.as_dict() for issue in issues],
                )
            else:
                print("ledger verification failed", file=sys.stderr)
                for issue in issues:
                    print(f"- {issue.path}: {issue.message}", file=sys.stderr)
            return 1

        if args.format == "json":
            print_envelope(
                output_format=args.format,
                ok=True,
                status="complete",
                artifact_paths=[ledger_path.resolve()]
                if ledger_path.exists()
                else [],
                details={"summary": ledger_summary(entries)},
            )
        else:
            print(format_ledger_summary(ledger_path, entries))
        return 0
    except LedgerError as exc:
        if args.format == "json":
            print_envelope(
                output_format=args.format,
                ok=False,
                status="error",
                issues=[{"path": str(ledger_path), "message": str(exc)}],
            )
        else:
            print(f"receipt ledger error: {exc}", file=sys.stderr)
        return 1


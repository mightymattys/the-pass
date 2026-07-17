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

def handle_audit(args: argparse.Namespace) -> int:
    try:
        report = reproduce_package(
            args.package,
            timeout_seconds=args.timeout_seconds,
            sandbox_launcher=args.sandbox_launcher,
            sandbox_policy=args.sandbox_policy,
        )
        write_json_atomic(args.output, report)
        passed = report["status"] == "pass"
        print_envelope(
            output_format=args.format,
            ok=passed,
            status=report["status"],
            artifact_paths=[args.output.resolve()],
            issues=(
                []
                if passed
                else [
                    {
                        "path": str(args.package),
                        "message": "clean reproduction did not match the tracked package",
                    }
                ]
            ),
        )
        return 0 if passed else 2
    except (OSError, ReproductionError, RuntimeError, TypeError, ValueError) as exc:
        print_envelope(
            output_format=args.format,
            ok=False,
            status="error",
            issues=[{"path": str(args.package), "message": str(exc)}],
        )
        return 1


def handle_robustness(args: argparse.Namespace) -> int:
    try:
        if args.robustness_command == "sweep":
            operator_ledger = (
                args.ledger.resolve()
                if args.ledger.is_absolute()
                else (repo_root_from(Path(__file__)) / args.ledger).resolve()
            )
            descriptor = load_document(args.descriptor)
            execution = load_document(args.execution)
            variants = json.loads(args.variants.read_text(encoding="utf-8"))
            splits = (
                json.loads(args.splits.read_text(encoding="utf-8"))
                if args.splits is not None
                else None
            )
            stress_results = (
                json.loads(args.stress_results.read_text(encoding="utf-8"))
                if args.stress_results is not None
                else []
            )
            if (
                not isinstance(descriptor, dict)
                or not isinstance(execution, dict)
                or not isinstance(variants, list)
                or not all(isinstance(row, dict) for row in variants)
                or (
                    splits is not None
                    and (
                        not isinstance(splits, list)
                        or not all(isinstance(row, dict) for row in splits)
                    )
                )
                or not isinstance(stress_results, list)
                or not all(isinstance(row, dict) for row in stress_results)
            ):
                raise ValueError("robustness sweep inputs have invalid structure")
            registration_path = args.output.with_name(
                f"{args.output.stem}.registration.json"
            )
            document = run_strategy_sweep(
                load_event_jsonl(args.events),
                descriptor=descriptor,
                execution=execution,
                variants=variants,
                splits=splits,
                selected_index=args.selected_index,
                registration_path=registration_path,
                workspace_root=args.workspace_root,
                timeout_seconds=args.timeout_seconds,
                source_package_id=(
                    build_run_entry(args.source_package)["package_id"]
                    if args.source_package is not None
                    else None
                ),
                created_at=args.created_at,
                train_size=args.train_size,
                test_size=args.test_size,
                purge=args.purge,
                embargo=args.embargo,
                null_variant_index=args.null_variant_index,
                stress_results=stress_results,
                ledger_path=operator_ledger,
                source_package_path=args.source_package,
                runtime_mode=args.runtime_mode,
                sandbox_launcher=args.sandbox_launcher,
                sandbox_policy=args.sandbox_policy,
            )
            write_json_atomic(args.output, document)
            validation = validate_artifact(
                args.output,
                artifact_type="robustness_report",
                ledger_path=operator_ledger,
            )
            if not validation.ok:
                details = "; ".join(
                    f"{issue.path}: {issue.message}"
                    for issue in validation.issues
                )
                raise ValueError(f"generated robustness report is invalid: {details}")
            blocked = document["status"] == "blocked"
            print_envelope(
                output_format=args.format,
                ok=not blocked,
                status=document["status"],
                artifact_paths=[registration_path.resolve(), args.output.resolve()],
                issues=[]
                if not blocked
                else [
                    {
                        "path": str(args.output),
                        "message": "one or more preregistered variants failed",
                    }
                ],
                details={"robustness": document},
            )
            return 2 if blocked else 0
        matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
        if (
            not isinstance(matrix, list)
            or not matrix
            or not all(isinstance(row, list) for row in matrix)
        ):
            raise ValueError("matrix must be a non-empty JSON array of arrays")
        if args.selected_index < 0 or args.selected_index >= len(matrix[0]):
            raise ValueError("selected-index is outside the variant columns")
        selected = [float(row[args.selected_index]) for row in matrix]
        trial_sharpes = []
        for column in range(len(matrix[0])):
            values = [float(row[column]) for row in matrix]
            average = sum(values) / len(values)
            variance = sum((value - average) ** 2 for value in values) / (
                len(values) - 1
            )
            trial_sharpes.append(average / variance**0.5 if variance else 0.0)
        document = {
            "pbo": cscv_pbo(matrix, blocks=args.blocks),
            "psr": probabilistic_sharpe_ratio(selected),
            "dsr": deflated_sharpe_ratio(selected, trial_sharpes=trial_sharpes),
            "reality_check": reality_check(matrix, bootstrap_samples=500, seed=7),
            "selected_index": args.selected_index,
            "tried_variants": len(matrix[0]),
        }
        write_json_atomic(args.output, document)
        print_envelope(
            output_format=args.format,
            ok=True,
            status="complete",
            artifact_paths=[args.output.resolve()],
        )
        return 0
    except (
        json.JSONDecodeError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        print_envelope(
            output_format=args.format,
            ok=False,
            status="error",
            issues=[
                {
                    "path": str(getattr(args, "matrix", getattr(args, "events", "robustness"))),
                    "message": str(exc),
                }
            ],
        )
        return 1


def handle_risk(args: argparse.Namespace) -> int:
    try:
        returns = json.loads(args.returns.read_text(encoding="utf-8"))
        scenarios = json.loads(args.scenarios.read_text(encoding="utf-8"))
        if not isinstance(returns, list) or not isinstance(scenarios, list):
            raise ValueError("returns and scenarios must be JSON arrays")
        policy = build_risk_policy_artifact(args.asset_class)
        report = build_risk_report(
            package_id=args.package_id,
            policy=policy,
            returns=[float(value) for value in returns],
            scenario_losses=scenarios,
            capacity=args.capacity,
            blockers=args.blocker,
        )
        output_dir = args.output_dir.resolve()
        policy_path = output_dir / "risk_policy.json"
        report_path = output_dir / "risk_report.json"
        write_json_atomic(policy_path, policy)
        write_json_atomic(report_path, report)
        print_envelope(
            output_format=args.format,
            ok=True,
            status=report["verdict"],
            artifact_paths=[policy_path, report_path],
        )
        return 2 if report["verdict"] in {"blocked", "revise", "kill"} else 0
    except (
        json.JSONDecodeError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        print_envelope(
            output_format=args.format,
            ok=False,
            status="error",
            issues=[{"path": str(args.returns), "message": str(exc)}],
        )
        return 1


def handle_candidate(args: argparse.Namespace) -> int:
    try:
        target, package_id = assemble_research_candidate(
            args.source,
            args.target,
            ledger_path=args.ledger,
            run_id=args.run_id,
            created_at=args.created_at,
            robustness_report_path=args.robustness_report,
            findings_path=args.findings,
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
    except (CandidateAssemblyError, LedgerError, OSError, ValueError) as exc:
        print_envelope(
            output_format=args.format,
            ok=False,
            status="error",
            issues=[{"path": str(args.target), "message": str(exc)}],
        )
        return 1


def handle_paper(args: argparse.Namespace) -> int:
    try:
        events = load_event_jsonl(args.events)
        risk_policy = json.loads(args.risk_policy.read_text(encoding="utf-8"))
        if args.paper_command == "observe":
            result = observe_strategy(
                events,
                batch_id=args.batch_id,
                descriptor_path=args.descriptor,
                execution_path=args.execution,
                risk_policy=risk_policy,
                observation_policy=ObservationPolicy(
                    args.max_staleness_ns,
                    args.max_clock_skew_ns,
                    args.max_outage_gap_ns,
                ),
                observation_time_ns=args.observation_time_ns,
                observation_dir=args.observation_dir,
                workspace_root=args.workspace_root,
                timeout_seconds=args.timeout_seconds,
                full_replay_interval_batches=args.full_replay_interval_batches,
            )
            frozen = result["status"] == "frozen"
            print_envelope(
                output_format=args.format,
                ok=not frozen,
                status=result.get("invocation_status", result["status"]),
                artifact_paths=[
                    args.observation_dir.resolve() / "observation.json",
                    args.observation_dir.resolve() / "current-result.json",
                ]
                if not frozen
                else [args.observation_dir.resolve() / "observation.json"],
                issues=[]
                if not frozen
                else [
                    {
                        "path": str(args.observation_dir),
                        "message": "paper observation froze closed",
                    }
                ],
                details={"observation": result},
            )
            return 2 if frozen else 0
        result = run_virtual_paper_process(
            strategy_name=args.strategy,
            events=events,
            risk_policy=risk_policy,
            observation_policy=ObservationPolicy(
                args.max_staleness_ns,
                args.max_clock_skew_ns,
                args.max_outage_gap_ns,
            ),
            observation_time_ns=args.observation_time_ns,
            output_path=args.output,
        )
        frozen = result["status"] == "frozen"
        print_envelope(
            output_format=args.format,
            ok=not frozen,
            status=result["status"],
            artifact_paths=[args.output.resolve()],
            issues=[]
            if not frozen
            else [
                {"path": str(args.output), "message": "paper observer froze closed"}
            ],
        )
        return 2 if frozen else 0
    except (
        json.JSONDecodeError,
        OSError,
        PaperObservationError,
        RuntimeError,
        TypeError,
        ValueError,
    ) as exc:
        print_envelope(
            output_format=args.format,
            ok=False,
            status="error",
            issues=[{"path": str(args.events), "message": str(exc)}],
        )
        return 1



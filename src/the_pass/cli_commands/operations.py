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

def handle_research(args: argparse.Namespace) -> int:
    try:
        report = build_research_evidence_report(args.registry)
        write_json_atomic(args.output, report)
        blocked = bool(
            args.require_promotion_evidence
            and report["promotion_eligible_count"] == 0
        )
        print_envelope(
            output_format=args.format,
            ok=not blocked,
            status="blocked" if blocked else "complete",
            artifact_paths=[args.output.resolve()],
            issues=[]
            if not blocked
            else [
                {
                    "path": str(args.registry),
                    "message": "no full-text source with an evidence locator",
                }
            ],
            details={"evidence": report},
        )
        return 2 if blocked else 0
    except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
        print_envelope(
            output_format=args.format,
            ok=False,
            status="error",
            issues=[{"path": str(args.registry), "message": str(exc)}],
        )
        return 1


def handle_automation(args: argparse.Namespace) -> int:
    try:
        document, path = run_automation_spec(
            args.spec,
            output_dir=args.output_dir,
            scheduled_for=args.scheduled_for,
            workspace_root=args.workspace_root,
        )
        ok = document["status"] in {"complete", "duplicate"}
        print_envelope(
            output_format=args.format,
            ok=ok,
            status=document["status"],
            artifact_paths=[path],
        )
        return 0 if ok else 2
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        print_envelope(
            output_format=args.format,
            ok=False,
            status="error",
            issues=[{"path": str(args.spec), "message": str(exc)}],
        )
        return 1


def handle_agents(args: argparse.Namespace) -> int:
    try:
        if args.agents_command == "doctor":
            document = doctor_agents(args.provider)
            print_envelope(
                output_format=args.format,
                ok=True,
                status="complete",
                details=document,
            )
            return 0
        if args.agents_command == "catalog-check":
            as_of = date.fromisoformat(args.as_of) if args.as_of else None
            document = model_catalog_status(as_of=as_of)
            print_envelope(
                output_format=args.format,
                ok=not document["stale"],
                status=document["status"],
                issues=[]
                if not document["stale"]
                else [
                    {
                        "path": "config/agent-orchestration.v1.yaml",
                        "message": "model catalog requires human review",
                    }
                ],
                details={"catalog": document},
            )
            return 2 if document["stale"] else 0
        if args.agents_command == "route":
            route = route_workflow_stage(
                args.stage,
                author_provider=args.author_provider,
                available_providers=args.available_providers or ("codex", "claude"),
            )
            print_envelope(
                output_format=args.format,
                ok=True,
                status="complete",
                details={"route": route},
            )
            return 0
        if args.agents_command == "inspect":
            document = inspect_agent_task(args.task)
            print_envelope(
                output_format=args.format,
                ok=True,
                status="complete",
                artifact_paths=[args.task.resolve()],
                details={"inspection": document},
            )
            return 0
        run, run_path, exit_code = dispatch_agent_task(
            args.task,
            output_dir=args.output_dir,
            execute=args.execute,
        )
        artifact_paths = [run_path]
        if run["patch"] is not None:
            artifact_paths.append(Path(run["patch"]["path"]))
        print_envelope(
            output_format=args.format,
            ok=exit_code == 0,
            status=run["status"],
            artifact_paths=artifact_paths,
            issues=[{"path": str(args.task), "message": issue} for issue in run["issues"]],
            receipt_id=run["run_id"],
            details={"agent_run": run},
        )
        return exit_code
    except AgentSafetyError as exc:
        print_envelope(
            output_format=args.format,
            ok=False,
            status="forbidden",
            issues=[{"path": str(getattr(args, "task", "agents")), "message": str(exc)}],
        )
        return 3
    except (AgentOrchestrationError, OSError, TypeError, ValueError) as exc:
        print_envelope(
            output_format=args.format,
            ok=False,
            status="error",
            issues=[{"path": str(getattr(args, "task", "agents")), "message": str(exc)}],
        )
        return 1


def handle_report_dashboard(args: argparse.Namespace) -> int:
    try:
        paths = build_static_dashboard(args.repo_root, args.output_dir)
        print_envelope(
            output_format=args.format,
            ok=True,
            status="complete",
            artifact_paths=paths,
        )
        return 0
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        print_envelope(
            output_format=args.format,
            ok=False,
            status="error",
            issues=[{"path": str(args.output_dir), "message": str(exc)}],
        )
        return 1



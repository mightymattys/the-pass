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

def handle_validate(args: argparse.Namespace) -> int:
    operator_ledger = (
        args.ledger.resolve()
        if args.ledger.is_absolute()
        else (repo_root_from(Path(__file__)) / args.ledger).resolve()
    )
    result = validate_artifact(
        args.artifact,
        schema_dir=args.schema_dir,
        artifact_type=args.type,
        ledger_path=operator_ledger,
    )
    artifact_type = result.artifact_type or "artifact"
    print_result(
        result,
        output_format=args.format,
        success_message=f"{args.artifact} validates as {artifact_type}",
        artifact_path=args.artifact,
    )
    return 0 if result.ok else 1


def handle_validate_package(args: argparse.Namespace) -> int:
    operator_ledger = (
        args.ledger.resolve()
        if args.ledger.is_absolute()
        else (repo_root_from(Path(__file__)) / args.ledger).resolve()
    )
    result = validate_package(
        args.package,
        schema_dir=args.schema_dir,
        ledger_path=operator_ledger,
    )
    print_result(
        result,
        output_format=args.format,
        success_message=f"{args.package} package validates",
        artifact_path=args.package,
    )
    return 0 if result.ok else 1


def handle_data(args: argparse.Namespace) -> int:
    if args.data_command == "ingest":
        if args.provider in {"binance", "polymarket"} and not args.network:
            print_envelope(
                output_format=args.format,
                ok=False,
                status="forbidden",
                issues=[
                    {
                        "path": str(args.request),
                        "message": "public provider ingest requires explicit --network",
                    }
                ],
            )
            return 3
        try:
            request = load_fetch_request(args.request)
            adapter = build_read_only_adapter(
                args.provider,
                archive_root=args.archive_root,
                licensed_archive=args.licensed_archive,
                license_reviewed=args.license_reviewed,
                resolution_reviewed=args.resolution_reviewed,
            )
            result = ingest_bundle(adapter, request, args.output)
            blocked = result.quality_report["promotion_impact"] == "blocked"
            print_envelope(
                output_format=args.format,
                ok=not blocked,
                status="blocked" if blocked else "complete",
                artifact_paths=[
                    result.raw_path,
                    result.canonical_path,
                    result.quality_path,
                    result.manifest_path,
                    result.receipt_path,
                    result.committed_path,
                ],
                issues=[]
                if not blocked
                else [
                    {
                        "path": str(result.quality_path),
                        "message": "ingested quality evidence blocks promotion",
                    }
                ],
                details={
                    "canonical_fingerprint": result.canonical_fingerprint,
                    "event_count": result.event_count,
                },
            )
            return 2 if blocked else 0
        except (json.JSONDecodeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            print_envelope(
                output_format=args.format,
                ok=False,
                status="error",
                issues=[{"path": str(args.request), "message": str(exc)}],
            )
            return 1
    if args.data_command == "plan":
        try:
            parameters = (
                json.loads(args.parameters.read_text(encoding="utf-8"))
                if args.parameters is not None
                else {}
            )
            if not isinstance(parameters, dict):
                raise ValueError("dataset plan parameters must be a JSON object")
            plan = build_dataset_plan(
                plan_id=args.id,
                provider=args.provider,
                kind=args.kind,
                instrument_id=args.instrument,
                start_ns=args.start_ns,
                end_ns=args.end_ns,
                chunk_ns=args.chunk_ns,
                created_at=args.created_at,
                limit=args.limit,
                parameters=parameters,
                expected_interval_ns=args.expected_interval_ns,
                cross_check_required=args.require_cross_check,
            )
            write_json_atomic(args.output, plan)
            print_envelope(
                output_format=args.format,
                ok=True,
                status="complete",
                artifact_paths=[args.output.resolve()],
                details={
                    "plan_fingerprint": plan["plan_fingerprint"],
                    "chunks": len(plan["requests"]),
                },
            )
            return 0
        except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
            print_envelope(
                output_format=args.format,
                ok=False,
                status="error",
                issues=[{"path": str(args.output), "message": str(exc)}],
            )
            return 1
    if args.data_command == "build":
        try:
            plan_document = json.loads(args.plan.read_text(encoding="utf-8"))
            if not isinstance(plan_document, dict):
                raise ValueError("dataset plan must be a JSON object")
            plan = validate_dataset_plan(plan_document)
            provider = str(plan["provider"])
            if provider in {"binance", "polymarket"} and not args.network:
                print_envelope(
                    output_format=args.format,
                    ok=False,
                    status="forbidden",
                    issues=[
                        {
                            "path": str(args.plan),
                            "message": "public provider dataset build requires explicit --network",
                        }
                    ],
                )
                return 3
            references = {}
            if args.cross_check_dir is not None:
                for descriptor in plan["requests"]:
                    path = args.cross_check_dir / f"{descriptor['chunk_id']}.json"
                    if path.is_file():
                        references[descriptor["chunk_id"]] = json.loads(
                            path.read_text(encoding="utf-8")
                        )
            adapter = build_read_only_adapter(
                provider,
                archive_root=args.archive_root,
                licensed_archive=args.licensed_archive,
                license_reviewed=args.license_reviewed,
                resolution_reviewed=args.resolution_reviewed,
            )
            result = build_dataset(
                adapter,
                plan,
                args.output,
                cross_check_references=references,
            )
            blocked = result.promotion_impact == "blocked"
            print_envelope(
                output_format=args.format,
                ok=not blocked,
                status="blocked" if blocked else "complete",
                artifact_paths=[
                    result.events_path,
                    result.quality_path,
                    result.manifest_path,
                    result.receipt_path,
                    result.committed_path,
                ],
                issues=(
                    [{"path": str(result.receipt_path), "message": "dataset evidence blocks promotion"}]
                    if blocked
                    else []
                ),
                details={
                    "dataset_fingerprint": result.dataset_fingerprint,
                    "event_count": result.event_count,
                    "fetched_chunks": result.fetched_chunks,
                    "resumed_chunks": result.resumed_chunks,
                },
            )
            return 2 if blocked else 0
        except (json.JSONDecodeError, OSError, RuntimeError, TypeError, ValueError) as exc:
            print_envelope(
                output_format=args.format,
                ok=False,
                status="error",
                issues=[{"path": str(args.plan), "message": str(exc)}],
            )
            return 1
    try:
        events = load_event_jsonl(args.events)
        policy = QualityPolicy(
            expected_interval_ns=args.expected_interval_ns,
            stale_after_ns=args.stale_after_ns,
            requested_start_ns=args.requested_start_ns,
            requested_end_ns=args.requested_end_ns,
        )
        report = build_quality_report(
            args.dataset_id, events, policy=policy, created_at=args.created_at
        )
        write_json_atomic(args.output, report)
        blocked = report["promotion_impact"] == "blocked"
        print_envelope(
            output_format=args.format,
            ok=not blocked,
            status=report["summary"]["status"],
            artifact_paths=[args.output.resolve()],
            issues=[]
            if not blocked
            else [
                {
                    "path": str(args.output),
                    "message": "quality report blocks promotion",
                }
            ],
        )
        return 2 if blocked else 0
    except (OSError, TypeError, ValueError) as exc:
        print_envelope(
            output_format=args.format,
            ok=False,
            status="error",
            issues=[{"path": str(args.events), "message": str(exc)}],
        )
        return 1


def handle_features(args: argparse.Namespace) -> int:
    try:
        events = load_event_jsonl(args.events)
        config = json.loads(args.config.read_text(encoding="utf-8"))
        if not isinstance(config, dict):
            raise ValueError("feature config must be a JSON object")
        result = build_bar_features(
            events,
            dataset_fingerprint=args.dataset_fingerprint,
            code_version=args.code_version,
            config=config,
            created_at=args.created_at,
        )
        output_dir = args.output_dir.resolve()
        rows_path = output_dir / "feature_rows.json"
        manifest_path = output_dir / "feature_manifest.json"
        write_json_atomic(rows_path, result.rows)
        write_json_atomic(manifest_path, result.manifest)
        print_envelope(
            output_format=args.format,
            ok=True,
            status="complete",
            artifact_paths=[rows_path, manifest_path],
        )
        return 0
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        print_envelope(
            output_format=args.format,
            ok=False,
            status="error",
            issues=[{"path": str(args.events), "message": str(exc)}],
        )
        return 1


def handle_screen(args: argparse.Namespace) -> int:
    try:
        closes = json.loads(args.closes.read_text(encoding="utf-8"))
        variants = json.loads(args.variants.read_text(encoding="utf-8"))
        if (
            not isinstance(closes, list)
            or not isinstance(variants, list)
            or not all(isinstance(item, dict) for item in variants)
        ):
            raise ValueError(
                "closes and variants must be JSON arrays; every variant must be an object"
            )
        from decimal import Decimal

        results = ReferenceScreenRunner().run(
            [Decimal(str(value)) for value in closes],
            family=args.family,
            variants=variants,
            fee_bps=Decimal(args.fee_bps),
        )
        write_json_atomic(args.output, results)
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
            issues=[{"path": str(args.closes), "message": str(exc)}],
        )
        return 1


def handle_backtest(args: argparse.Namespace) -> int:
    try:
        if args.backtest_command == "baseline":
            package = run_baseline(args.name, args.output)
        else:
            from decimal import Decimal

            artifact_inputs = (
                (args.strategy_spec, "strategy_spec"),
                (args.data_manifest, "data_manifest"),
                (args.quality_report, "quality_report"),
            )
            for path, artifact_type in artifact_inputs:
                validation = validate_artifact(path, artifact_type=artifact_type)
                if not validation.ok:
                    details = "; ".join(
                        f"{issue.path}: {issue.message}" for issue in validation.issues
                    )
                    raise ValueError(f"invalid {artifact_type}: {details}")
            strategy_spec = load_document(args.strategy_spec)
            data_manifest = load_document(args.data_manifest)
            quality_report = load_document(args.quality_report)
            descriptor = load_document(args.descriptor)
            execution = load_document(args.execution)
            if not all(
                isinstance(document, dict)
                for document in (
                    strategy_spec,
                    data_manifest,
                    quality_report,
                    descriptor,
                    execution,
                )
            ):
                raise ValueError("backtest inputs must be JSON or YAML objects")
            search_space = {
                "schema_version": 1,
                "registered_at": str(data_manifest["created_at"]),
                "family": str(strategy_spec["edge"]["primary_family"]),
                "variants": [descriptor["config"]],
                "selection_policy": "single user variant registered before execution",
                "selected_variant_id": 0,
            }
            preregister_search_space(args.output, search_space)
            worker_result = run_strategy_verified(
                args.events,
                descriptor=descriptor,
                execution=execution,
                workspace_root=args.workspace_root,
                timeout_seconds=args.timeout_seconds,
                output_limit_bytes=args.output_limit_bytes,
                runtime_mode=args.runtime_mode,
                sandbox_launcher=args.sandbox_launcher,
                sandbox_policy=args.sandbox_policy,
            )
            result = runner_result_from_document(worker_result)
            events = load_event_jsonl(args.events)
            evidence_fields = {
                "schema_version",
                "status",
                "runtime_version",
                "strategy_id",
                "strategy_source_sha256",
                "descriptor_fingerprint",
                "strategy_config_fingerprint",
                "execution_fingerprint",
                "risk_fingerprint",
                "events_fingerprint",
                "process_isolated",
                "credentials_present",
                "network_or_order_modules_loaded",
                "isolation",
                "runtime_promotion_eligible",
                "promotion_eligible",
                "promotion_status",
                "result_fingerprint",
                "determinism_verified",
                "execution",
            }
            runtime_evidence = {
                key: value for key, value in worker_result.items() if key in evidence_fields
            }
            workspace_root = args.workspace_root.resolve()
            strategy_source = (
                workspace_root / str(descriptor["strategy_file"])
            ).resolve()
            try:
                strategy_source.relative_to(workspace_root)
            except ValueError as exc:
                raise ValueError("strategy source escapes workspace root") from exc
            package = write_run_package(
                args.output,
                result=result,
                events=events,
                search_space=search_space,
                initial_cash=Decimal(str(execution["initial_cash"])),
                asset_class=str(descriptor["asset_class"]),
                random_seed=None,
                verdict="blocked",
                strategy_spec_document=strategy_spec,
                data_manifest_document=data_manifest,
                quality_report_document=quality_report,
                command="the-pass backtest run --descriptor <descriptor> --events <canonical-events>",
                runtime_evidence=runtime_evidence,
                reproduction_inputs={
                    "descriptor": descriptor,
                    "execution": execution,
                    "strategy_source": strategy_source,
                },
                created_at=str(data_manifest["created_at"]),
            )
        print_envelope(
            output_format=args.format,
            ok=True,
            status="complete",
            artifact_paths=[package],
        )
        return 0
    except (OSError, RuntimeError, StrategyRuntimeError, TypeError, ValueError) as exc:
        print_envelope(
            output_format=args.format,
            ok=False,
            status="error",
            issues=[{"path": str(args.output), "message": str(exc)}],
        )
        return 1



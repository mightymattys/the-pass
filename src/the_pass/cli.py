"""Command line interface for The Pass."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

from . import __version__
from .automation import run_automation_spec
from .data.contracts import CanonicalEvent
from .data.features import build_bar_features
from .data.quality import QualityPolicy, build_quality_report
from .engine.screen import ReferenceScreenRunner
from .engine.workflows import BASELINE_NAMES, run_baseline
from .incident import build_incident_report
from .paper import ObservationPolicy, run_virtual_paper_process
from .reporting import build_static_dashboard
from .risk import build_risk_policy_artifact, build_risk_report
from .robustness import (
    cscv_pbo,
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
    reality_check,
)
from .ledger import (
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
from .gates import (
    CORE_GATES,
    DEFAULT_POLICY_PATH,
    GateEvaluationError,
    evaluate_gate,
    write_gate_decision,
)
from .orchestration import (
    ForbiddenWorkflowError,
    WorkflowError,
    advance_workflow_state,
    create_superseding_package,
    new_workflow_state,
    read_workflow_state,
    write_workflow_state_atomic,
)
from .validator import (
    ARTIFACT_TYPES,
    ValidationResult,
    validate_artifact,
    validate_package,
)


def write_json_atomic(path: Path, document: object) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
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


def load_event_jsonl(path: Path) -> list[CanonicalEvent]:
    events = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            document = json.loads(line)
            if not isinstance(document, dict):
                raise ValueError("event must be an object")
            events.append(CanonicalEvent.from_dict(document))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"{path}:{line_number}: {exc}") from exc
    if not events:
        raise ValueError(f"{path}: no canonical events")
    return events


def print_envelope(
    *,
    output_format: str,
    ok: bool,
    status: str,
    artifact_paths: list[Path] | None = None,
    issues: list[dict[str, str]] | None = None,
    receipt_id: str | None = None,
    details: dict[str, object] | None = None,
) -> None:
    document = {
        **(details or {}),
        "ok": ok,
        "status": status,
        "artifact_paths": [str(path) for path in artifact_paths or []],
        "issues": issues or [],
        "receipt_id": receipt_id,
    }
    if output_format == "json":
        print(json.dumps(document, indent=2, sort_keys=True))
    else:
        stream = sys.stdout if ok else sys.stderr
        print(status, file=stream)
        for path in artifact_paths or []:
            print(f"- {path}", file=stream)
        for issue in issues or []:
            print(
                f"- {issue.get('path', '$')}: {issue.get('message', '')}", file=stream
            )


def print_result(
    result: ValidationResult,
    *,
    output_format: str,
    success_message: str,
    artifact_path: Path,
) -> None:
    if output_format == "json":
        print_envelope(
            output_format=output_format,
            ok=result.ok,
            status="valid" if result.ok else "invalid",
            artifact_paths=[artifact_path.resolve()],
            issues=[issue.as_dict() for issue in result.issues],
            details={
                "artifact_type": result.artifact_type,
                "schema_id": result.schema_id,
            },
        )
        return

    if result.ok:
        print(success_message)
        return

    print("validation failed", file=sys.stderr)
    for issue in result.issues:
        print(f"- {issue.path}: {issue.message}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="the-pass", description="Validate The Pass artifacts and packages."
    )
    parser.add_argument(
        "--version", action="version", version=f"the-pass {__version__}"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate one artifact.")
    validate_parser.add_argument(
        "artifact", type=Path, help="Artifact path, JSON or YAML."
    )
    validate_parser.add_argument(
        "--type",
        choices=sorted(ARTIFACT_TYPES),
        help="Artifact type. If omitted, inferred from filename or fields.",
    )
    validate_parser.add_argument(
        "--schema-dir", type=Path, help="Override schema directory."
    )
    validate_parser.add_argument(
        "--format", choices=("text", "json"), default="text", help="Output format."
    )

    package_parser = subparsers.add_parser(
        "validate-package", help="Validate a run package directory."
    )
    package_parser.add_argument("package", type=Path, help="Package directory.")
    package_parser.add_argument(
        "--schema-dir", type=Path, help="Override schema directory."
    )
    package_parser.add_argument(
        "--format", choices=("text", "json"), default="text", help="Output format."
    )

    data_parser = subparsers.add_parser(
        "data", help="Build and validate canonical data evidence."
    )
    data_subparsers = data_parser.add_subparsers(dest="data_command", required=True)
    data_quality = data_subparsers.add_parser(
        "quality", help="Build a quality report from canonical JSONL events."
    )
    data_quality.add_argument("events", type=Path, help="Canonical event JSONL path.")
    data_quality.add_argument("--dataset-id", required=True)
    data_quality.add_argument(
        "--created-at", required=True, help="Deterministic RFC 3339 report timestamp."
    )
    data_quality.add_argument("--output", type=Path, required=True)
    data_quality.add_argument("--expected-interval-ns", type=int)
    data_quality.add_argument("--stale-after-ns", type=int)
    data_quality.add_argument("--requested-start-ns", type=int)
    data_quality.add_argument("--requested-end-ns", type=int)
    data_quality.add_argument("--format", choices=("text", "json"), default="text")

    features_parser = subparsers.add_parser(
        "features", help="Build deterministic reference features."
    )
    features_subparsers = features_parser.add_subparsers(
        dest="features_command", required=True
    )
    features_build = features_subparsers.add_parser(
        "build", help="Build bar features and a feature manifest."
    )
    features_build.add_argument("events", type=Path, help="Canonical event JSONL path.")
    features_build.add_argument("--dataset-fingerprint", required=True)
    features_build.add_argument("--code-version", required=True)
    features_build.add_argument(
        "--config", type=Path, required=True, help="JSON feature configuration."
    )
    features_build.add_argument(
        "--created-at", required=True, help="Deterministic RFC 3339 manifest timestamp."
    )
    features_build.add_argument("--output-dir", type=Path, required=True)
    features_build.add_argument("--format", choices=("text", "json"), default="text")

    screen_parser = subparsers.add_parser(
        "screen", help="Run pre-registered vectorized diagnostic screens."
    )
    screen_subparsers = screen_parser.add_subparsers(
        dest="screen_command", required=True
    )
    screen_run = screen_subparsers.add_parser(
        "run", help="Evaluate every variant in a JSON parameter grid."
    )
    screen_run.add_argument(
        "--closes",
        type=Path,
        required=True,
        help="JSON array of decimal close strings.",
    )
    screen_run.add_argument(
        "--variants", type=Path, required=True, help="JSON array of parameter objects."
    )
    screen_run.add_argument(
        "--family",
        choices=("buy_hold", "random", "donchian", "mean_reversion"),
        required=True,
    )
    screen_run.add_argument("--fee-bps", default="10")
    screen_run.add_argument("--output", type=Path, required=True)
    screen_run.add_argument("--format", choices=("text", "json"), default="text")

    backtest_parser = subparsers.add_parser(
        "backtest", help="Run deterministic event-simulation baselines."
    )
    backtest_subparsers = backtest_parser.add_subparsers(
        dest="backtest_command", required=True
    )
    backtest_baseline = backtest_subparsers.add_parser(
        "baseline", help="Build one complete baseline evidence package."
    )
    backtest_baseline.add_argument("--name", choices=BASELINE_NAMES, required=True)
    backtest_baseline.add_argument(
        "--output", type=Path, required=True, help="New package directory."
    )
    backtest_baseline.add_argument("--format", choices=("text", "json"), default="text")

    robustness_parser = subparsers.add_parser(
        "robustness", help="Evaluate multiple testing and selection bias."
    )
    robustness_subparsers = robustness_parser.add_subparsers(
        dest="robustness_command", required=True
    )
    robustness_evaluate = robustness_subparsers.add_parser(
        "evaluate", help="Compute PBO, PSR, DSR, and Reality Check."
    )
    robustness_evaluate.add_argument(
        "--matrix",
        type=Path,
        required=True,
        help="JSON observations-by-variants return matrix.",
    )
    robustness_evaluate.add_argument("--selected-index", type=int, required=True)
    robustness_evaluate.add_argument("--blocks", type=int, default=8)
    robustness_evaluate.add_argument("--output", type=Path, required=True)
    robustness_evaluate.add_argument(
        "--format", choices=("text", "json"), default="text"
    )

    risk_parser = subparsers.add_parser(
        "risk", help="Build versioned strategy-independent risk evidence."
    )
    risk_subparsers = risk_parser.add_subparsers(dest="risk_command", required=True)
    risk_build = risk_subparsers.add_parser(
        "build", help="Build a risk policy and report from return/scenario JSON."
    )
    risk_build.add_argument(
        "--returns", type=Path, required=True, help="JSON return array."
    )
    risk_build.add_argument(
        "--scenarios", type=Path, required=True, help="JSON scenario result array."
    )
    risk_build.add_argument("--package-id", required=True)
    risk_build.add_argument(
        "--asset-class",
        choices=(
            "crypto_intraday",
            "crypto_funding",
            "listed_futures",
            "prediction_market",
        ),
        required=True,
    )
    risk_build.add_argument("--capacity", type=float, required=True)
    risk_build.add_argument("--blocker", action="append", default=[])
    risk_build.add_argument("--output-dir", type=Path, required=True)
    risk_build.add_argument("--format", choices=("text", "json"), default="text")

    paper_parser = subparsers.add_parser(
        "paper", help="Run the isolated virtual paper worker."
    )
    paper_subparsers = paper_parser.add_subparsers(dest="paper_command", required=True)
    paper_run = paper_subparsers.add_parser(
        "run", help="Run canonical JSONL through a baseline strategy in isolation."
    )
    paper_run.add_argument(
        "--strategy",
        choices=tuple(
            name for name in BASELINE_NAMES if name != "prediction_complement"
        ),
        required=True,
    )
    paper_run.add_argument("--events", type=Path, required=True)
    paper_run.add_argument("--risk-policy", type=Path, required=True)
    paper_run.add_argument("--observation-time-ns", type=int, required=True)
    paper_run.add_argument("--max-staleness-ns", type=int, required=True)
    paper_run.add_argument("--max-clock-skew-ns", type=int, required=True)
    paper_run.add_argument("--max-outage-gap-ns", type=int, required=True)
    paper_run.add_argument("--output", type=Path, required=True)
    paper_run.add_argument("--format", choices=("text", "json"), default="text")

    automation_parser = subparsers.add_parser(
        "automation", help="Run a scheduler-neutral whitelisted job."
    )
    automation_subparsers = automation_parser.add_subparsers(
        dest="automation_command", required=True
    )
    automation_run = automation_subparsers.add_parser(
        "run", help="Run one AutomationSpec."
    )
    automation_run.add_argument("spec", type=Path)
    automation_run.add_argument("--output-dir", type=Path, required=True)
    automation_run.add_argument("--scheduled-for", required=True)
    automation_run.add_argument("--workspace-root", type=Path, default=Path.cwd())
    automation_run.add_argument("--format", choices=("text", "json"), default="text")

    report_parser = subparsers.add_parser(
        "report", help="Build a read-only static evidence report bundle."
    )
    report_subparsers = report_parser.add_subparsers(
        dest="report_command", required=True
    )
    report_build = report_subparsers.add_parser("build")
    report_build.add_argument("--repo-root", type=Path, default=Path.cwd())
    report_build.add_argument("--output-dir", type=Path, required=True)
    report_build.add_argument("--format", choices=("text", "json"), default="text")

    dashboard_parser = subparsers.add_parser(
        "dashboard", help="Build the read-only static dashboard."
    )
    dashboard_subparsers = dashboard_parser.add_subparsers(
        dest="dashboard_command", required=True
    )
    dashboard_build = dashboard_subparsers.add_parser("build")
    dashboard_build.add_argument("--repo-root", type=Path, default=Path.cwd())
    dashboard_build.add_argument("--output-dir", type=Path, required=True)
    dashboard_build.add_argument("--format", choices=("text", "json"), default="text")

    incident_parser = subparsers.add_parser(
        "incident", help="Create fail-closed incident evidence."
    )
    incident_subparsers = incident_parser.add_subparsers(
        dest="incident_command", required=True
    )
    incident_create = incident_subparsers.add_parser("create")
    incident_create.add_argument("--id", required=True)
    incident_create.add_argument(
        "--severity", choices=("P0", "P1", "P2", "P3"), required=True
    )
    incident_create.add_argument("--detected-at", required=True)
    incident_create.add_argument("--source", required=True)
    incident_create.add_argument("--summary", required=True)
    incident_create.add_argument("--evidence", action="append", required=True)
    incident_create.add_argument("--freeze-reason", required=True)
    incident_create.add_argument("--output", type=Path, required=True)
    incident_create.add_argument("--format", choices=("text", "json"), default="text")

    workflow_parser = subparsers.add_parser(
        "workflow", help="Manage deterministic slash-skill workflow state."
    )
    workflow_subparsers = workflow_parser.add_subparsers(
        dest="workflow_command", required=True
    )
    workflow_start = workflow_subparsers.add_parser(
        "start", help="Create a new bounded workflow state."
    )
    workflow_start.add_argument("--state", type=Path, required=True)
    workflow_start.add_argument("--run-id", required=True)
    workflow_start.add_argument("--strategy-id", default="pending")
    workflow_start.add_argument("--objective", required=True)
    workflow_start.add_argument("--target-gate", choices=CORE_GATES, required=True)
    workflow_start.add_argument("--strategy-owner", required=True)
    workflow_start.add_argument("--run-owner", required=True)
    workflow_start.add_argument("--ledger", type=Path, required=True)
    workflow_start.add_argument("--started-at")
    workflow_start.add_argument("--format", choices=("text", "json"), default="text")

    workflow_advance = workflow_subparsers.add_parser(
        "advance", help="Apply one validated workflow transition."
    )
    workflow_advance.add_argument("--state", type=Path, required=True)
    workflow_advance.add_argument("--to-stage")
    workflow_advance.add_argument(
        "--status",
        choices=("in_progress", "waiting", "blocked", "killed", "complete"),
        required=True,
    )
    workflow_advance.add_argument("--next-action", required=True)
    workflow_advance.add_argument("--reviewer")
    workflow_advance.add_argument("--evidence", action="append", default=[])
    workflow_advance.add_argument("--blocker", action="append", default=[])
    workflow_advance.add_argument("--package-path")
    workflow_advance.add_argument("--package-id")
    workflow_advance.add_argument("--remediation", action="store_true")
    workflow_advance.add_argument("--resume", action="store_true")
    workflow_advance.add_argument(
        "--moved-gate", choices=("true", "false"), default="false"
    )
    workflow_advance.add_argument("--updated-at")
    workflow_advance.add_argument("--format", choices=("text", "json"), default="text")

    workflow_status = workflow_subparsers.add_parser(
        "status", help="Validate and display workflow state."
    )
    workflow_status.add_argument("--state", type=Path, required=True)
    workflow_status.add_argument("--format", choices=("text", "json"), default="text")

    workflow_fingerprint = workflow_subparsers.add_parser(
        "fingerprint", help="Compute a validated package identity without recording it."
    )
    workflow_fingerprint.add_argument("package", type=Path)
    workflow_fingerprint.add_argument(
        "--format", choices=("text", "json"), default="text"
    )

    workflow_supersede = workflow_subparsers.add_parser(
        "supersede",
        help="Create a mutable successor without changing a recorded package.",
    )
    workflow_supersede.add_argument("source", type=Path)
    workflow_supersede.add_argument("target", type=Path)
    workflow_supersede.add_argument("--ledger", type=Path, required=True)
    workflow_supersede.add_argument("--run-id", required=True)
    workflow_supersede.add_argument("--created-at", required=True)
    workflow_supersede.add_argument(
        "--format", choices=("text", "json"), default="text"
    )

    gate_parser = subparsers.add_parser(
        "gate", help="Evaluate artifact-backed promotion gates."
    )
    gate_subparsers = gate_parser.add_subparsers(dest="gate_command", required=True)
    gate_evaluate = gate_subparsers.add_parser(
        "evaluate", help="Evaluate a package and write a gate decision."
    )
    gate_evaluate.add_argument(
        "package", type=Path, help="Package directory containing the gate evidence."
    )
    gate_evaluate.add_argument(
        "--gate", choices=CORE_GATES, required=True, help="Canonical gate to evaluate."
    )
    gate_evaluate.add_argument(
        "--reviewer", required=True, help="Independent reviewer identifier."
    )
    gate_evaluate.add_argument(
        "--policy",
        type=Path,
        default=DEFAULT_POLICY_PATH,
        help="Versioned gate policy.",
    )
    gate_evaluate.add_argument(
        "--ledger",
        type=Path,
        default=DEFAULT_LEDGER_PATH,
        help="Receipt ledger for prior gates.",
    )
    gate_evaluate.add_argument(
        "--output", type=Path, required=True, help="Decision file inside the package."
    )
    gate_evaluate.add_argument(
        "--format", choices=("text", "json"), default="text", help="Output format."
    )

    receipts_parser = subparsers.add_parser(
        "receipts", help="Summarize or update the append-only receipt ledger."
    )
    receipts_parser.add_argument(
        "--ledger", type=Path, default=DEFAULT_LEDGER_PATH, help="Ledger JSONL path."
    )
    receipts_parser.add_argument(
        "--format", choices=("text", "json"), default="text", help="Output format."
    )
    receipts_subparsers = receipts_parser.add_subparsers(dest="receipts_command")

    receipts_add = receipts_subparsers.add_parser(
        "add", help="Validate a package and append its receipt."
    )
    receipts_add.add_argument("package", type=Path, help="Package directory.")
    receipts_add.add_argument(
        "--ledger", dest="sub_ledger", type=Path, help="Ledger JSONL path."
    )

    receipts_add_decision = receipts_subparsers.add_parser(
        "add-decision", help="Validate and append an artifact-backed gate decision."
    )
    receipts_add_decision.add_argument(
        "decision", type=Path, help="Gate decision artifact inside its package."
    )
    receipts_add_decision.add_argument(
        "--ledger", dest="sub_ledger", type=Path, help="Ledger JSONL path."
    )

    receipts_verify = receipts_subparsers.add_parser(
        "verify", help="Verify the ledger hash chain."
    )
    receipts_verify.add_argument(
        "--ledger", dest="sub_ledger", type=Path, help="Ledger JSONL path."
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "validate":
        result = validate_artifact(
            args.artifact, schema_dir=args.schema_dir, artifact_type=args.type
        )
        artifact_type = result.artifact_type or "artifact"
        print_result(
            result,
            output_format=args.format,
            success_message=f"{args.artifact} validates as {artifact_type}",
            artifact_path=args.artifact,
        )
        return 0 if result.ok else 1

    if args.command == "validate-package":
        result = validate_package(args.package, schema_dir=args.schema_dir)
        print_result(
            result,
            output_format=args.format,
            success_message=f"{args.package} package validates",
            artifact_path=args.package,
        )
        return 0 if result.ok else 1

    if args.command == "data":
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

    if args.command == "features":
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

    if args.command == "screen":
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

    if args.command == "backtest":
        try:
            package = run_baseline(args.name, args.output)
            print_envelope(
                output_format=args.format,
                ok=True,
                status="complete",
                artifact_paths=[package],
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

    if args.command == "robustness":
        try:
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
                issues=[{"path": str(args.matrix), "message": str(exc)}],
            )
            return 1

    if args.command == "risk":
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

    if args.command == "paper":
        try:
            events = load_event_jsonl(args.events)
            risk_policy = json.loads(args.risk_policy.read_text(encoding="utf-8"))
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

    if args.command == "automation":
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

    if args.command in {"report", "dashboard"}:
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

    if args.command == "incident":
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

    if args.command == "workflow":
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

    if args.command == "gate":
        try:
            package_dir = args.package.resolve()
            output_path = args.output.resolve()
            if output_path.parent != package_dir:
                raise GateEvaluationError(
                    "gate decision output must be stored in the package directory"
                )
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
        except GateEvaluationError as exc:
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

    if args.command == "receipts":
        ledger_path = getattr(args, "sub_ledger", None) or args.ledger
        try:
            if args.receipts_command == "add":
                append_result = append_ledger_entry(ledger_path, args.package)
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
                append_result = append_gate_decision(ledger_path, args.decision)
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
                issues = verify_ledger_file(ledger_path)
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

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

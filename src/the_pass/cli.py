"""Command line interface for The Pass."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


from . import __version__
from .attestation import (
    ATTESTABLE_GATES,
)
from .data.contracts import CanonicalEvent
from .adapters.base import FetchRequest
from .engine.workflows import BASELINE_NAMES
from .ledger import (
    DEFAULT_LEDGER_PATH,
)
from .gates import (
    CORE_GATES,
    DEFAULT_POLICY_PATH,
)
from .validator import (
    ARTIFACT_TYPES,
    ValidationResult,
)




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


def load_fetch_request(path: Path) -> FetchRequest:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError("fetch request must be a JSON object")
    allowed = {"kind", "instrument_id", "start_ns", "end_ns", "limit", "parameters"}
    unknown = set(document) - allowed
    if unknown:
        raise ValueError(f"unknown fetch request fields: {', '.join(sorted(unknown))}")
    if not isinstance(document.get("kind"), str) or not document["kind"]:
        raise ValueError("fetch request kind must be a non-empty string")
    for field in ("start_ns", "end_ns", "limit"):
        value = document.get(field)
        if value is not None and (
            not isinstance(value, int) or isinstance(value, bool) or value < 0
        ):
            raise ValueError(f"fetch request {field} must be a non-negative integer")
    if document.get("limit") == 0:
        raise ValueError("fetch request limit must be positive")
    if (
        document.get("start_ns") is not None
        and document.get("end_ns") is not None
        and document["start_ns"] >= document["end_ns"]
    ):
        raise ValueError("fetch request requires start_ns < end_ns")
    if document.get("parameters") is not None and not isinstance(
        document["parameters"], dict
    ):
        raise ValueError("fetch request parameters must be an object")
    return FetchRequest(**document)


def build_read_only_adapter(
    provider: str,
    *,
    archive_root: Path | None,
    licensed_archive: bool,
    license_reviewed: bool,
    resolution_reviewed: bool,
):
    if provider == "binance":
        from .adapters.binance_spot import BinanceSpotAdapter

        return BinanceSpotAdapter(license_reviewed=license_reviewed)
    if provider == "polymarket":
        from .adapters.polymarket import PolymarketAdapter

        return PolymarketAdapter(
            license_reviewed=license_reviewed,
            resolution_reviewed=resolution_reviewed,
        )
    from .adapters.databento_futures import DatabentoCompatibleFuturesAdapter

    if archive_root is None:
        raise ValueError("futures ingest requires --archive-root")
    return DatabentoCompatibleFuturesAdapter(
        archive_root, licensed_archive=licensed_archive
    )


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
    validate_parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER_PATH)
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
    package_parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER_PATH)
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
    data_ingest = data_subparsers.add_parser(
        "ingest", help="Build one immutable adapter evidence bundle."
    )
    data_ingest.add_argument(
        "--provider", choices=("binance", "polymarket", "futures"), required=True
    )
    data_ingest.add_argument(
        "--request", type=Path, required=True, help="JSON FetchRequest object."
    )
    data_ingest.add_argument("--output", type=Path, required=True)
    data_ingest.add_argument("--archive-root", type=Path)
    data_ingest.add_argument("--network", action="store_true")
    data_ingest.add_argument("--licensed-archive", action="store_true")
    data_ingest.add_argument("--license-reviewed", action="store_true")
    data_ingest.add_argument("--resolution-reviewed", action="store_true")
    data_ingest.add_argument("--format", choices=("text", "json"), default="text")
    data_plan = data_subparsers.add_parser(
        "plan", help="Create deterministic non-overlapping ingest chunks."
    )
    data_plan.add_argument("--id", required=True)
    data_plan.add_argument("--provider", choices=("binance", "polymarket", "futures"), required=True)
    data_plan.add_argument("--kind", required=True)
    data_plan.add_argument("--instrument", required=True)
    data_plan.add_argument("--start-ns", type=int, required=True)
    data_plan.add_argument("--end-ns", type=int, required=True)
    data_plan.add_argument("--chunk-ns", type=int, required=True)
    data_plan.add_argument("--created-at", required=True)
    data_plan.add_argument("--limit", type=int)
    data_plan.add_argument("--expected-interval-ns", type=int)
    data_plan.add_argument("--parameters", type=Path)
    data_plan.add_argument("--require-cross-check", action="store_true")
    data_plan.add_argument("--output", type=Path, required=True)
    data_plan.add_argument("--format", choices=("text", "json"), default="text")
    data_build = data_subparsers.add_parser(
        "build", help="Fetch or resume every planned chunk and publish one dataset."
    )
    data_build.add_argument("--plan", type=Path, required=True)
    data_build.add_argument("--output", type=Path, required=True)
    data_build.add_argument("--cross-check-dir", type=Path)
    data_build.add_argument("--archive-root", type=Path)
    data_build.add_argument("--network", action="store_true")
    data_build.add_argument("--licensed-archive", action="store_true")
    data_build.add_argument("--license-reviewed", action="store_true")
    data_build.add_argument("--resolution-reviewed", action="store_true")
    data_build.add_argument("--format", choices=("text", "json"), default="text")

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
    backtest_run = backtest_subparsers.add_parser(
        "run", help="Run a trusted local strategy twice and build diagnostic evidence."
    )
    backtest_run.add_argument("--descriptor", type=Path, required=True)
    backtest_run.add_argument("--strategy-spec", type=Path, required=True)
    backtest_run.add_argument("--events", type=Path, required=True)
    backtest_run.add_argument("--data-manifest", type=Path, required=True)
    backtest_run.add_argument("--quality-report", type=Path, required=True)
    backtest_run.add_argument("--execution", type=Path, required=True)
    backtest_run.add_argument("--workspace-root", type=Path, default=Path.cwd())
    backtest_run.add_argument("--output", type=Path, required=True)
    backtest_run.add_argument("--timeout-seconds", type=float, default=60.0)
    backtest_run.add_argument("--output-limit-bytes", type=int, default=5_000_000)
    backtest_run.add_argument(
        "--runtime-mode",
        choices=("trusted_local", "hardened"),
        default="trusted_local",
    )
    backtest_run.add_argument("--sandbox-launcher", type=Path)
    backtest_run.add_argument("--sandbox-policy", type=Path)
    backtest_run.add_argument("--format", choices=("text", "json"), default="text")

    audit_parser = subparsers.add_parser(
        "audit", help="Reproduce and independently inspect run packages."
    )
    audit_subparsers = audit_parser.add_subparsers(dest="audit_command", required=True)
    audit_reproduce = audit_subparsers.add_parser(
        "reproduce", help="Rebuild a custom run in a clean temporary workspace."
    )
    audit_reproduce.add_argument("package", type=Path)
    audit_reproduce.add_argument("--output", type=Path, required=True)
    audit_reproduce.add_argument("--timeout-seconds", type=int, default=120)
    audit_reproduce.add_argument("--sandbox-launcher", type=Path)
    audit_reproduce.add_argument("--sandbox-policy", type=Path)
    audit_reproduce.add_argument("--format", choices=("text", "json"), default="text")

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
    robustness_sweep = robustness_subparsers.add_parser(
        "sweep", help="Build a preregistered return matrix by executing a custom strategy."
    )
    robustness_sweep.add_argument("--descriptor", type=Path, required=True)
    robustness_sweep.add_argument("--events", type=Path, required=True)
    robustness_sweep.add_argument("--execution", type=Path, required=True)
    robustness_sweep.add_argument("--variants", type=Path, required=True)
    robustness_sweep.add_argument("--splits", type=Path)
    robustness_sweep.add_argument("--source-package", type=Path)
    robustness_sweep.add_argument("--created-at")
    robustness_sweep.add_argument("--train-size", type=int)
    robustness_sweep.add_argument("--test-size", type=int)
    robustness_sweep.add_argument("--purge", type=int, default=0)
    robustness_sweep.add_argument("--embargo", type=int, default=0)
    robustness_sweep.add_argument("--null-variant-index", type=int)
    robustness_sweep.add_argument("--stress-results", type=Path)
    robustness_sweep.add_argument(
        "--ledger", type=Path, default=DEFAULT_LEDGER_PATH
    )
    robustness_sweep.add_argument("--selected-index", type=int, required=True)
    robustness_sweep.add_argument("--workspace-root", type=Path, default=Path.cwd())
    robustness_sweep.add_argument("--timeout-seconds", type=float, default=60.0)
    robustness_sweep.add_argument(
        "--runtime-mode",
        choices=("trusted_local", "hardened"),
        default="trusted_local",
    )
    robustness_sweep.add_argument("--sandbox-launcher", type=Path)
    robustness_sweep.add_argument("--sandbox-policy", type=Path)
    robustness_sweep.add_argument("--output", type=Path, required=True)
    robustness_sweep.add_argument("--format", choices=("text", "json"), default="text")

    candidate_parser = subparsers.add_parser(
        "candidate", help="Assemble immutable promotion candidates from measured evidence."
    )
    candidate_subparsers = candidate_parser.add_subparsers(
        dest="candidate_command", required=True
    )
    candidate_assemble = candidate_subparsers.add_parser(
        "assemble",
        help="Create a validated research candidate successor without manual package edits.",
    )
    candidate_assemble.add_argument("source", type=Path)
    candidate_assemble.add_argument("target", type=Path)
    candidate_assemble.add_argument("--ledger", type=Path, required=True)
    candidate_assemble.add_argument("--run-id", required=True)
    candidate_assemble.add_argument("--created-at", required=True)
    candidate_assemble.add_argument(
        "--robustness-report", type=Path, required=True
    )
    candidate_assemble.add_argument("--findings", type=Path, required=True)
    candidate_assemble.add_argument(
        "--trusted-reviewers",
        type=Path,
        help="Operator-controlled reviewer registry used to verify an existing ledger.",
    )
    candidate_assemble.add_argument(
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

    research_parser = subparsers.add_parser(
        "research", help="Audit the scope and promotion strength of research evidence."
    )
    research_subparsers = research_parser.add_subparsers(
        dest="research_command", required=True
    )
    research_evidence = research_subparsers.add_parser(
        "evidence", help="Build a conservative source-evidence scope report."
    )
    research_evidence.add_argument("--registry", type=Path, required=True)
    research_evidence.add_argument("--output", type=Path, required=True)
    research_evidence.add_argument("--require-promotion-evidence", action="store_true")
    research_evidence.add_argument("--format", choices=("text", "json"), default="text")

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
    paper_observe = paper_subparsers.add_parser(
        "observe", help="Append one immutable batch to a resumable custom-strategy observation."
    )
    paper_observe.add_argument("--descriptor", type=Path, required=True)
    paper_observe.add_argument("--events", type=Path, required=True)
    paper_observe.add_argument("--batch-id", required=True)
    paper_observe.add_argument("--execution", type=Path, required=True)
    paper_observe.add_argument("--risk-policy", type=Path, required=True)
    paper_observe.add_argument("--observation-dir", type=Path, required=True)
    paper_observe.add_argument("--workspace-root", type=Path, default=Path.cwd())
    paper_observe.add_argument("--observation-time-ns", type=int, required=True)
    paper_observe.add_argument("--max-staleness-ns", type=int, required=True)
    paper_observe.add_argument("--max-clock-skew-ns", type=int, required=True)
    paper_observe.add_argument("--max-outage-gap-ns", type=int, required=True)
    paper_observe.add_argument("--timeout-seconds", type=float, default=60.0)
    paper_observe.add_argument(
        "--full-replay-interval-batches", type=int, default=10
    )
    paper_observe.add_argument("--format", choices=("text", "json"), default="text")

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

    agents_parser = subparsers.add_parser(
        "agents", help="Inspect or run bounded Codex/Claude delegation."
    )
    agents_subparsers = agents_parser.add_subparsers(
        dest="agents_command", required=True
    )
    agents_doctor = agents_subparsers.add_parser(
        "doctor", help="Check local provider binaries without model calls."
    )
    agents_doctor.add_argument(
        "--provider", choices=("codex", "claude", "all"), default="all"
    )
    agents_doctor.add_argument("--format", choices=("text", "json"), default="text")
    agents_catalog = agents_subparsers.add_parser(
        "catalog-check", help="Fail closed when the reviewed model catalog is stale."
    )
    agents_catalog.add_argument(
        "--as-of", help="Optional ISO date for deterministic maintenance checks."
    )
    agents_catalog.add_argument("--format", choices=("text", "json"), default="text")
    agents_route = agents_subparsers.add_parser(
        "route", help="Resolve the provider and model for one workflow stage."
    )
    agents_route.add_argument("--stage", required=True)
    agents_route.add_argument("--author-provider", choices=("codex", "claude"))
    agents_route.add_argument(
        "--available-provider",
        choices=("codex", "claude"),
        action="append",
        dest="available_providers",
    )
    agents_route.add_argument("--format", choices=("text", "json"), default="text")
    agents_inspect = agents_subparsers.add_parser(
        "inspect", help="Validate a task and preview its safe invocation."
    )
    agents_inspect.add_argument("task", type=Path)
    agents_inspect.add_argument("--format", choices=("text", "json"), default="text")
    agents_dispatch = agents_subparsers.add_parser(
        "dispatch", help="Execute one bounded external-agent task."
    )
    agents_dispatch.add_argument("task", type=Path)
    agents_dispatch.add_argument("--output-dir", type=Path, required=True)
    agents_dispatch.add_argument("--execute", action="store_true")
    agents_dispatch.add_argument("--format", choices=("text", "json"), default="text")

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

    workflow_execute = workflow_subparsers.add_parser(
        "execute", help="Supervise a trusted stage driver to a terminal checkpoint."
    )
    workflow_execute.add_argument("--state", type=Path, required=True)
    workflow_execute.add_argument("--cwd", type=Path, default=Path.cwd())
    workflow_execute.add_argument("--report", type=Path)
    workflow_execute.add_argument("--author-provider", choices=("codex", "claude"))
    workflow_execute.add_argument(
        "--available-provider",
        choices=("codex", "claude"),
        action="append",
        dest="available_providers",
    )
    workflow_execute.add_argument("--max-cycles", type=int)
    workflow_execute.add_argument("--timeout-seconds", type=int, default=1800)
    workflow_execute.add_argument("--max-output-bytes", type=int, default=4194304)
    workflow_execute.add_argument("--execute", action="store_true")
    workflow_execute.add_argument("--format", choices=("text", "json"), default="text")
    workflow_execute.add_argument(
        "--driver",
        nargs=argparse.REMAINDER,
        required=True,
        help="Trusted driver argv. This option must be last.",
    )

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
        "--trusted-reviewers",
        type=Path,
        help="Operator-controlled reviewer registry used to verify an existing ledger.",
    )
    workflow_supersede.add_argument(
        "--format", choices=("text", "json"), default="text"
    )

    gate_parser = subparsers.add_parser(
        "gate", help="Evaluate artifact-backed promotion gates."
    )
    gate_subparsers = gate_parser.add_subparsers(dest="gate_command", required=True)
    gate_keygen = gate_subparsers.add_parser(
        "keygen", help="Create an Ed25519 reviewer key and public identity registry."
    )
    gate_keygen.add_argument("--registry-id", required=True)
    gate_keygen.add_argument("--reviewer", required=True)
    gate_keygen.add_argument(
        "--principal-type", choices=("provider", "human"), required=True
    )
    gate_keygen.add_argument("--provider", required=True)
    gate_keygen.add_argument("--created-at", required=True)
    gate_keygen.add_argument("--valid-from", required=True)
    gate_keygen.add_argument("--valid-until", required=True)
    gate_keygen.add_argument("--private-key-output", type=Path, required=True)
    gate_keygen.add_argument("--registry-output", type=Path, required=True)
    gate_keygen.add_argument("--format", choices=("text", "json"), default="text")
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
        "--trusted-reviewers",
        type=Path,
        help="Operator-controlled reviewer registry outside the evaluated package.",
    )
    gate_evaluate.add_argument(
        "--output", type=Path, required=True, help="Decision file inside the package."
    )
    gate_evaluate.add_argument(
        "--format", choices=("text", "json"), default="text", help="Output format."
    )
    gate_attest = gate_subparsers.add_parser(
        "attest", help="Sign reviewer provenance for a non-live promotion gate."
    )
    gate_attest.add_argument("package", type=Path)
    gate_attest.add_argument("--gate", choices=ATTESTABLE_GATES, required=True)
    gate_attest.add_argument("--reviewer", required=True)
    gate_attest.add_argument(
        "--principal-type", choices=("provider", "human"), required=True
    )
    gate_attest.add_argument("--provider", required=True)
    gate_attest.add_argument("--model", required=True)
    gate_attest.add_argument("--run-id", required=True)
    gate_attest.add_argument("--author-provider", required=True)
    gate_attest.add_argument("--reviewer-provider", required=True)
    gate_attest.add_argument("--state-before", type=Path, required=True)
    gate_attest.add_argument("--state-after", type=Path, required=True)
    gate_attest.add_argument("--task-evidence", type=Path, required=True)
    gate_attest.add_argument("--stdout-evidence", type=Path)
    gate_attest.add_argument("--stderr-evidence", type=Path)
    gate_attest.add_argument("--key-registry", type=Path, required=True)
    gate_attest.add_argument(
        "--ledger",
        type=Path,
        default=DEFAULT_LEDGER_PATH,
        help="Operator-controlled robustness registration ledger.",
    )
    gate_attest.add_argument("--created-at")
    gate_attest.add_argument("--output", type=Path, required=True)
    gate_attest.add_argument(
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
    receipts_add.add_argument(
        "--trusted-reviewers",
        type=Path,
        help="Operator-controlled reviewer registry used to verify existing gate decisions.",
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
    receipts_add_decision.add_argument(
        "--trusted-reviewers",
        type=Path,
        help="Operator-controlled reviewer registry used to replay the decision.",
    )

    receipts_verify = receipts_subparsers.add_parser(
        "verify", help="Verify the ledger hash chain."
    )
    receipts_verify.add_argument(
        "--ledger", dest="sub_ledger", type=Path, help="Ledger JSONL path."
    )
    receipts_verify.add_argument(
        "--trusted-reviewers",
        type=Path,
        help="Operator-controlled reviewer registry used to replay gate decisions.",
    )

    from .cli_commands import COMMAND_HANDLERS

    for command, handler in COMMAND_HANDLERS.items():
        subparsers.choices[command].set_defaults(func=handler)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

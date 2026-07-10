"""Artifact and package validation for The Pass."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

from .adapter_contract import validate_adapter_contract

_VERSIONED_ARTIFACTS = (
    "adapter",
    "source_note",
    "hypothesis",
    "strategy_spec",
    "data_manifest",
    "run_receipt",
    "metrics_report",
    "cost_waterfall",
    "verdict_report",
    "screen_report",
    "findings",
    "refire_ticket",
    "simmer_laps",
    "paper_plan",
    "observation_manifest",
    "divergence_report",
    "approval_pack",
    "receipt_summary",
)

ARTIFACT_SCHEMAS = {
    artifact_type: {
        1: f"{artifact_type}.schema.json",
        2: f"{artifact_type}.v2.schema.json",
    }
    for artifact_type in _VERSIONED_ARTIFACTS
}
ARTIFACT_SCHEMAS["gate_decision"] = {2: "gate_decision.v2.schema.json"}
ARTIFACT_SCHEMAS["research_brief"] = {2: "research_brief.v2.schema.json"}
ARTIFACT_SCHEMAS["audit_report"] = {2: "audit_report.v2.schema.json"}
ARTIFACT_SCHEMAS["canonical_event"] = {2: "canonical_event.v2.schema.json"}
ARTIFACT_SCHEMAS["instrument_registry"] = {2: "instrument_registry.v2.schema.json"}
ARTIFACT_SCHEMAS["quality_report"] = {2: "quality_report.v2.schema.json"}
ARTIFACT_SCHEMAS["feature_manifest"] = {2: "feature_manifest.v2.schema.json"}
ARTIFACT_SCHEMAS["risk_policy"] = {2: "risk_policy.v2.schema.json"}
ARTIFACT_SCHEMAS["risk_report"] = {2: "risk_report.v2.schema.json"}
ARTIFACT_SCHEMAS["automation_spec"] = {2: "automation_spec.v2.schema.json"}
ARTIFACT_SCHEMAS["automation_run"] = {2: "automation_run.v2.schema.json"}
ARTIFACT_SCHEMAS["incident_report"] = {2: "incident_report.v2.schema.json"}
ARTIFACT_SCHEMAS["human_decision"] = {2: "human_decision.v2.schema.json"}
ARTIFACT_SCHEMAS["config_diff"] = {2: "config_diff.v2.schema.json"}
ARTIFACT_SCHEMAS["dry_run_proof"] = {2: "dry_run_proof.v2.schema.json"}
ARTIFACT_SCHEMAS["live_risk_contract"] = {2: "live_risk_contract.v2.schema.json"}
ARTIFACT_TYPES = {
    artifact_type: versions[max(versions)]
    for artifact_type, versions in ARTIFACT_SCHEMAS.items()
}

PACKAGE_CORE_ARTIFACTS = (
    "strategy_spec",
    "data_manifest",
    "run_receipt",
    "metrics_report",
    "cost_waterfall",
    "verdict_report",
)

PACKAGE_OPTIONAL_ARTIFACTS = ("adapter", "source_note", "findings")
ARTIFACT_EXTENSIONS = (".json", ".yaml", ".yml")

FORMAT_CHECKER = FormatChecker()
RFC3339_DATETIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$"
)


@FORMAT_CHECKER.checks("date-time")
def _is_rfc3339_datetime(value: Any) -> bool:
    if not isinstance(value, str):
        return True
    if RFC3339_DATETIME.fullmatch(value) is None:
        return False
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        return False
    return True


@dataclass(frozen=True)
class ValidationIssue:
    """A validation issue suitable for human or machine output."""

    path: str
    message: str
    severity: str = "error"

    def as_dict(self) -> dict[str, str]:
        return {"path": self.path, "message": self.message, "severity": self.severity}


@dataclass(frozen=True)
class ValidationResult:
    """Validation result for one artifact or package."""

    ok: bool
    issues: list[ValidationIssue]
    artifact_type: str | None = None
    schema_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "artifact_type": self.artifact_type,
            "schema_id": self.schema_id,
            "issues": [issue.as_dict() for issue in self.issues],
        }


class ArtifactValidationError(Exception):
    """Raised when an artifact cannot be loaded or validated."""


def repo_root_from(start: Path | None = None) -> Path:
    """Find the repository root from a path inside the repo."""

    current = (start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / ".codex-plugin" / "plugin.json").exists() and (candidate / "schemas").exists():
            return candidate
    return Path.cwd().resolve()


def default_schema_dir() -> Path:
    repo_root = repo_root_from(Path(__file__).resolve())
    repo_schemas = repo_root / "schemas"
    plugin_manifest = repo_root / ".codex-plugin" / "plugin.json"
    try:
        plugin = json.loads(plugin_manifest.read_text(encoding="utf-8"))
        if isinstance(plugin, dict) and plugin.get("name") == "the-pass" and repo_schemas.is_dir():
            return repo_schemas
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass
    return Path(__file__).resolve().parent / "schemas"


def load_document(path: Path) -> Any:
    """Load a JSON or YAML document."""

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ArtifactValidationError(f"cannot read {path}: {exc}") from exc

    try:
        if path.suffix.lower() == ".json":
            return json.loads(text)
        if path.suffix.lower() in {".yaml", ".yml"}:
            return yaml.safe_load(text)
    except (json.JSONDecodeError, yaml.YAMLError) as exc:
        raise ArtifactValidationError(f"cannot parse {path}: {exc}") from exc

    raise ArtifactValidationError(f"unsupported artifact extension for {path}")


def load_schema(schema_dir: Path, artifact_type: str, schema_version: int) -> dict[str, Any]:
    versions = ARTIFACT_SCHEMAS.get(artifact_type)
    if versions is None:
        raise ArtifactValidationError(f"unknown artifact type: {artifact_type}")
    schema_name = versions.get(schema_version)
    if schema_name is None:
        supported = ", ".join(str(version) for version in sorted(versions))
        raise ArtifactValidationError(
            f"unsupported schema_version {schema_version} for {artifact_type}; supported: {supported}"
        )
    schema_path = schema_dir / schema_name
    if not schema_path.exists():
        raise ArtifactValidationError(f"missing schema: {schema_path}")
    document = load_document(schema_path)
    if not isinstance(document, dict):
        raise ArtifactValidationError(f"schema is not an object: {schema_path}")
    return document


def detect_artifact_type(path: Path, document: Any) -> str | None:
    """Detect artifact type from filename first, then from distinctive keys."""

    stem = path.stem
    if stem in ARTIFACT_TYPES:
        return stem

    if not isinstance(document, dict):
        return None

    keys = set(document)
    if {"mode", "asset_classes", "providers", "engine", "policies", "safety"} <= keys:
        return "adapter"
    if {"type", "priority", "status", "claim", "evidence", "required_tests"} <= keys:
        return "source_note"
    if {"status", "proposed_name", "source_notes", "edge", "market", "test", "risks", "kill_when", "blockers"} <= keys:
        return "hypothesis"
    if {"market", "edge", "data", "signal", "execution", "risk", "validation", "gates"} <= keys:
        return "strategy_spec"
    if {"dataset_name", "source", "coverage", "schema", "quality", "fingerprint"} <= keys:
        return "data_manifest"
    if {"strategy_spec", "code_version", "data_manifest", "outputs", "safety"} <= keys:
        return "run_receipt"
    if {"sample", "gross_metrics", "net_metrics", "robustness"} <= keys:
        return "metrics_report"
    if {"gross_pnl", "costs", "net_pnl", "assumptions"} <= keys:
        return "cost_waterfall"
    if {"verdict", "gate_results", "evidence", "risks", "next_action"} <= keys:
        return "verdict_report"
    if {"strategy_spec", "mode", "sample", "variants", "baseline", "costs", "results", "decision", "safety"} <= keys:
        return "screen_report"
    if {"package", "reviewer", "target_gate", "findings", "summary"} <= keys:
        return "findings"
    if {"source_finding", "package", "target_gate", "scope", "fix_plan", "result"} <= keys:
        return "refire_ticket"
    if {"target_gate", "package", "budget", "laps", "final"} <= keys:
        return "simmer_laps"
    if {"source_package", "strategy_spec", "adapter", "config_hash", "observation", "decision_logic", "divergence_policy", "safety", "status"} <= keys:
        return "paper_plan"
    if {"paper_plan", "source_package", "data_capture", "signals", "simulated_orders", "quality"} <= keys:
        return "observation_manifest"
    if {"paper_plan", "observation_manifest", "sample", "comparisons", "breaches", "decision"} <= keys:
        return "divergence_report"
    if {"strategy_id", "requested_gate", "config_hash", "adapter", "evidence", "risk_limits", "operations", "human_decisions_required", "status"} <= keys:
        return "approval_pack"
    if {"ledger", "filters", "summary", "packages", "status"} <= keys:
        return "receipt_summary"
    if {"gate_id", "gate_result", "policy_version", "policy_hash", "package_id", "evidence", "reviewer"} <= keys:
        return "gate_decision"
    if {"topic", "objective", "sources", "hypotheses", "evidence_gaps", "next_tests", "status"} <= keys:
        return "research_brief"
    if {"target", "reviewer", "findings", "verdict", "evidence", "limitations"} <= keys:
        return "audit_report"
    if {"source", "venue", "asset_class", "instrument_id", "event_type", "event_time_ns", "receive_time_ns", "ingest_id", "payload"} <= keys:
        return "canonical_event"
    if {"registry_id", "instruments", "fingerprint"} <= keys:
        return "instrument_registry"
    if {"dataset_id", "checks", "summary", "quarantine", "promotion_impact"} <= keys:
        return "quality_report"
    if {"dataset_fingerprint", "code_version", "config_hash", "features", "output_fingerprint"} <= keys:
        return "feature_manifest"
    if {"policy_id", "policy_version", "asset_class", "sizing", "limits", "stress", "policy_hash"} <= keys:
        return "risk_policy"
    if {"package_id", "policy_id", "policy_hash", "drawdown_distribution", "expected_shortfall", "scenario_losses", "verdict"} <= keys:
        return "risk_report"
    if {"owner", "trigger", "command", "inputs", "allowed_writes", "forbidden_actions", "timeout_seconds", "retry_policy", "alert_sink", "freeze_procedure"} <= keys:
        return "automation_spec"
    if {"automation_spec", "idempotency_key", "started_at", "finished_at", "attempts", "status", "outputs", "receipt"} <= keys:
        return "automation_run"
    if {"severity", "detected_at", "source", "summary", "timeline", "impact", "evidence", "actions", "status"} <= keys:
        return "incident_report"
    if {"venue", "account_scope", "adapter", "config_hash", "decision", "accepted_live_capability_adr", "grants_live_approval"} <= keys:
        return "human_decision"
    if {"before_hash", "after_hash", "changes", "review_required", "secrets_present"} <= keys:
        return "config_diff"
    if {"gateway", "config_hash", "intent_fingerprint", "external_side_effects", "transport_available", "result"} <= keys:
        return "dry_run_proof"
    if {"account_equity", "micro_notional_cap", "daily_loss_cap", "max_leverage", "freeze_conditions", "policy_hash"} <= keys:
        return "live_risk_contract"
    return None


def validate_workflow_artifact(artifact_type: str, document: dict[str, Any]) -> list[ValidationIssue]:
    """Check workflow invariants that are awkward or unclear in JSON Schema."""

    issues: list[ValidationIssue] = []

    if artifact_type == "metrics_report" and document.get("schema_version") == 2:
        reasons = document["not_applicable_reasons"]
        for group_name in ("gross_metrics", "net_metrics"):
            for metric_name, value in document[group_name].items():
                reason_key = f"{group_name}.{metric_name}"
                if value is None and not reasons.get(reason_key):
                    issues.append(
                        ValidationIssue(
                            f"$.not_applicable_reasons.{reason_key}",
                            "must explain every null v2 metric",
                        )
                    )
                if value is not None and not is_finite_number(value):
                    issues.append(
                        ValidationIssue(
                            f"$.{group_name}.{metric_name}",
                            "must be a finite number or null",
                        )
                    )

    if artifact_type == "screen_report":
        decision = document["decision"]
        if decision["status"] == "backtest_candidate" and not document["variants"]["tried"]:
            issues.append(ValidationIssue("$.variants.tried", "must record at least one tried variant"))

    if artifact_type == "findings":
        summary = document["summary"]
        blocking = [
            finding
            for finding in document["findings"]
            if finding["blocks_promotion"] and finding["status"] in {"open", "confirmed"}
        ]
        if summary["gate_result"] == "pass" and blocking:
            issues.append(ValidationIssue("$.summary.gate_result", "cannot pass with unresolved blocking findings"))

    if artifact_type == "simmer_laps":
        if len(document["laps"]) > document["budget"]["max_laps"]:
            issues.append(ValidationIssue("$.laps", "cannot exceed budget.max_laps"))
        lap_numbers = [lap["lap"] for lap in document["laps"]]
        if lap_numbers != list(range(1, len(lap_numbers) + 1)):
            issues.append(ValidationIssue("$.laps", "lap numbers must be contiguous and start at 1"))
        movement = [lap["moved_gate"] for lap in document["laps"]]
        if document["final"]["status"] == "passed" and not any(movement):
            issues.append(ValidationIssue("$.final.status", "cannot pass when no lap moved the target gate"))
        if any(not movement[index] and not movement[index + 1] for index in range(len(movement) - 1)):
            issues.append(ValidationIssue("$.laps", "must stop after two consecutive no-progress laps"))

    if artifact_type == "paper_plan":
        decision_logic = document["decision_logic"]
        if not decision_logic["same_as_backtest"] and not decision_logic["differences"]:
            issues.append(
                ValidationIssue(
                    "$.decision_logic.differences",
                    "must document differences when paper logic differs from backtest",
                )
            )

    if artifact_type == "divergence_report":
        blocking_breaches = [breach for breach in document["breaches"] if breach["blocks_promotion"]]
        if document["decision"]["status"] == "risk_review_candidate" and blocking_breaches:
            issues.append(
                ValidationIssue(
                    "$.decision.status",
                    "cannot be risk_review_candidate while a blocking divergence breach exists",
                )
            )

    if artifact_type == "receipt_summary":
        if document["summary"]["entries"] != len(document["packages"]):
            issues.append(ValidationIssue("$.summary.entries", "must equal the number of package rows"))

    return issues


def is_finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def schema_path(error: ValidationError) -> str:
    if not error.absolute_path:
        return "$"
    return "$." + ".".join(str(part) for part in error.absolute_path)


def validate_artifact(
    artifact_path: Path,
    *,
    schema_dir: Path | None = None,
    artifact_type: str | None = None,
) -> ValidationResult:
    issues: list[ValidationIssue] = []
    schema_dir = (schema_dir or default_schema_dir()).resolve()
    artifact_path = artifact_path.resolve()

    try:
        document = load_document(artifact_path)
    except ArtifactValidationError as exc:
        return ValidationResult(False, [ValidationIssue(str(artifact_path), str(exc))], artifact_type)

    if not isinstance(document, dict):
        return ValidationResult(
            False,
            [ValidationIssue(str(artifact_path), "artifact document must be an object")],
            artifact_type,
        )

    detected_type = artifact_type or detect_artifact_type(artifact_path, document)
    if detected_type is None:
        return ValidationResult(
            False,
            [
                ValidationIssue(
                    str(artifact_path),
                    "could not detect artifact type; pass --type "
                    + "|".join(sorted(ARTIFACT_TYPES)),
                )
            ],
            None,
        )

    if detected_type not in ARTIFACT_TYPES:
        return ValidationResult(
            False,
            [ValidationIssue(str(artifact_path), f"unknown artifact type: {detected_type}")],
            detected_type,
        )

    schema_version = document.get("schema_version")
    if not isinstance(schema_version, int) or isinstance(schema_version, bool):
        return ValidationResult(
            False,
            [ValidationIssue("$.schema_version", "must be an integer")],
            detected_type,
        )

    try:
        schema = load_schema(schema_dir, detected_type, schema_version)
    except ArtifactValidationError as exc:
        return ValidationResult(False, [ValidationIssue(str(artifact_path), str(exc))], detected_type)

    validator = Draft202012Validator(schema, format_checker=FORMAT_CHECKER)
    for error in sorted(validator.iter_errors(document), key=lambda item: list(item.absolute_path)):
        issues.append(ValidationIssue(schema_path(error), error.message))

    if not issues:
        if detected_type == "adapter":
            for issue in validate_adapter_contract(document):
                issues.append(ValidationIssue(issue.path, issue.message, issue.severity))
        elif detected_type in {
            "metrics_report",
            "screen_report",
            "findings",
            "refire_ticket",
            "simmer_laps",
            "paper_plan",
            "observation_manifest",
            "divergence_report",
            "approval_pack",
            "receipt_summary",
        }:
            issues.extend(validate_workflow_artifact(detected_type, document))

    schema_id = schema.get("$id")
    return ValidationResult(not issues, issues, detected_type, schema_id if isinstance(schema_id, str) else None)


def find_artifact(package_dir: Path, artifact_type: str) -> Path | None:
    for extension in ARTIFACT_EXTENSIONS:
        candidate = package_dir / f"{artifact_type}{extension}"
        if candidate.exists():
            return candidate
    return None


def resolve_package_link(package_dir: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    return (package_dir / value).resolve()


def link_exists(package_dir: Path, value: Any) -> bool:
    resolved = resolve_package_link(package_dir, value)
    if resolved is None:
        return False
    try:
        resolved.relative_to(package_dir.resolve())
    except ValueError:
        return False
    return resolved.exists()


def require_exact_artifact_link(
    package_dir: Path,
    value: Any,
    expected_path: Path,
    issue_path: str,
    issues: list[ValidationIssue],
) -> None:
    resolved = resolve_package_link(package_dir, value)
    if resolved is None or resolved != expected_path.resolve():
        issues.append(ValidationIssue(issue_path, f"must reference {expected_path.name}"))


def require_false_flag(document: dict[str, Any], section: str, field: str, issues: list[ValidationIssue]) -> None:
    section_value = document.get(section)
    if not isinstance(section_value, dict) or section_value.get(field) is not False:
        issues.append(ValidationIssue(f"$.{section}.{field}", "must be false"))


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or RFC3339_DATETIME.fullmatch(value) is None:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError:
        return None


def require_ordered_interval(
    start: Any,
    end: Any,
    path: str,
    issues: list[ValidationIssue],
) -> tuple[datetime, datetime] | None:
    parsed_start = parse_timestamp(start)
    parsed_end = parse_timestamp(end)
    if parsed_start is None or parsed_end is None:
        issues.append(ValidationIssue(path, "must contain RFC 3339 start and end timestamps"))
        return None
    if parsed_start >= parsed_end:
        issues.append(ValidationIssue(path, "start must be earlier than end"))
        return None
    return parsed_start, parsed_end


def validate_package(package_dir: Path, *, schema_dir: Path | None = None) -> ValidationResult:
    package_dir = package_dir.resolve()
    schema_dir = (schema_dir or default_schema_dir()).resolve()
    issues: list[ValidationIssue] = []

    if not package_dir.exists() or not package_dir.is_dir():
        return ValidationResult(False, [ValidationIssue(str(package_dir), "package directory does not exist")], "package")

    artifact_paths: dict[str, Path] = {}
    for artifact_type in (*PACKAGE_CORE_ARTIFACTS, *PACKAGE_OPTIONAL_ARTIFACTS):
        matches: list[Path] = []
        for extension in ARTIFACT_EXTENSIONS:
            candidate = package_dir / f"{artifact_type}{extension}"
            if not candidate.exists():
                continue
            try:
                candidate.resolve().relative_to(package_dir)
            except ValueError:
                issues.append(
                    ValidationIssue(
                        str(candidate),
                        f"artifact {artifact_type} escapes package directory",
                    )
                )
                continue
            matches.append(candidate)
        if len(matches) > 1:
            issues.append(
                ValidationIssue(
                    str(package_dir),
                    f"ambiguous artifact {artifact_type}: " + ", ".join(path.name for path in matches),
                )
            )
        if matches:
            artifact_paths[artifact_type] = matches[0]

    for artifact_type in PACKAGE_CORE_ARTIFACTS:
        if artifact_type not in artifact_paths:
            issues.append(
                ValidationIssue(
                    str(package_dir),
                    f"missing required artifact: {artifact_type}.json|yaml|yml",
                )
            )

    documents: dict[str, dict[str, Any]] = {}
    for artifact_type, path in sorted(artifact_paths.items()):
        result = validate_artifact(path, schema_dir=schema_dir, artifact_type=artifact_type)
        issues.extend(ValidationIssue(f"{path.name}:{issue.path}", issue.message) for issue in result.issues)
        if result.ok:
            loaded = load_document(path)
            if isinstance(loaded, dict):
                documents[artifact_type] = loaded

    if issues:
        return ValidationResult(False, issues, "package")

    receipt = documents["run_receipt"]
    strategy_spec = documents["strategy_spec"]
    metrics = documents["metrics_report"]
    costs = documents["cost_waterfall"]
    data_manifest = documents["data_manifest"]
    verdict = documents["verdict_report"]

    sample = metrics.get("sample", {})
    sample_interval = require_ordered_interval(
        sample.get("start_time") if isinstance(sample, dict) else None,
        sample.get("end_time") if isinstance(sample, dict) else None,
        "$.metrics_report.sample",
        issues,
    )
    coverage = data_manifest.get("coverage", {})
    coverage_interval = require_ordered_interval(
        coverage.get("start_time") if isinstance(coverage, dict) else None,
        coverage.get("end_time") if isinstance(coverage, dict) else None,
        "$.data_manifest.coverage",
        issues,
    )
    if sample_interval and coverage_interval and (
        sample_interval[0] < coverage_interval[0] or sample_interval[1] > coverage_interval[1]
    ):
        issues.append(
            ValidationIssue(
                "$.metrics_report.sample",
                "sample window must be contained by data manifest coverage",
            )
        )

    require_exact_artifact_link(
        package_dir,
        receipt.get("strategy_spec"),
        artifact_paths["strategy_spec"],
        "$.run_receipt.strategy_spec",
        issues,
    )
    require_exact_artifact_link(
        package_dir,
        receipt.get("data_manifest"),
        artifact_paths["data_manifest"],
        "$.run_receipt.data_manifest",
        issues,
    )

    outputs = receipt.get("outputs")
    if not isinstance(outputs, dict):
        issues.append(ValidationIssue("$.run_receipt.outputs", "must be an object"))
    else:
        for output_field in ("metrics_report", "cost_waterfall", "verdict_report"):
            require_exact_artifact_link(
                package_dir,
                outputs.get(output_field),
                artifact_paths[output_field],
                f"$.run_receipt.outputs.{output_field}",
                issues,
            )

    for field in ("live_trading_enabled", "real_order_path_available", "credentials_available"):
        require_false_flag(receipt, "safety", field, issues)

    for artifact_type, document in (("metrics_report", metrics), ("cost_waterfall", costs), ("verdict_report", verdict)):
        if document.get("run_receipt") != artifact_paths["run_receipt"].name:
            issues.append(
                ValidationIssue(
                    f"$.{artifact_type}.run_receipt",
                    f"must reference {artifact_paths['run_receipt'].name}",
                )
            )

    linked_source_note_documents: list[dict[str, Any]] = []
    evidence = verdict.get("evidence")
    if not isinstance(evidence, dict):
        issues.append(ValidationIssue("$.verdict_report.evidence", "must be an object"))
    else:
        for field in ("metrics_report", "cost_waterfall", "data_manifest"):
            require_exact_artifact_link(
                package_dir,
                evidence.get(field),
                artifact_paths[field],
                f"$.verdict_report.evidence.{field}",
                issues,
            )
        source_notes = evidence.get("source_notes", [])
        if not isinstance(source_notes, list):
            issues.append(ValidationIssue("$.verdict_report.evidence.source_notes", "must be an array"))
        else:
            for index, source_note in enumerate(source_notes):
                source_note_path = resolve_package_link(package_dir, source_note)
                if source_note_path is None or not link_exists(package_dir, source_note):
                    issues.append(
                        ValidationIssue(
                            f"$.verdict_report.evidence.source_notes[{index}]",
                            "linked source note does not exist",
                        )
                    )
                    continue
                source_result = validate_artifact(source_note_path, schema_dir=schema_dir, artifact_type="source_note")
                issues.extend(
                    ValidationIssue(
                        f"{source_note_path.name}:{issue.path}",
                        issue.message,
                    )
                    for issue in source_result.issues
                )
                if source_result.ok:
                    source_document = load_document(source_note_path)
                    if isinstance(source_document, dict):
                        linked_source_note_documents.append(source_document)

    adapter = documents.get("adapter")
    if adapter is not None:
        adapter_safety = adapter.get("safety")
        if not isinstance(adapter_safety, dict):
            issues.append(ValidationIssue("$.adapter.safety", "must be an object"))
        else:
            for field in ("live_trading_enabled", "real_order_path_available", "credentials_required"):
                if adapter_safety.get(field) is not False:
                    issues.append(ValidationIssue(f"$.adapter.safety.{field}", "must be false for public packages"))

        if adapter.get("mode") == "diagnostic" and verdict.get("verdict") == "paper_candidate":
            issues.append(
                ValidationIssue(
                    "$.verdict_report.verdict",
                    "diagnostic adapters cannot produce paper_candidate verdicts",
                )
            )

    if verdict.get("verdict") == "paper_candidate":
        non_v2 = sorted(
            artifact_type
            for artifact_type in PACKAGE_CORE_ARTIFACTS
            if documents[artifact_type].get("schema_version") != 2
        )
        if non_v2:
            issues.append(
                ValidationIssue(
                    "$.schema_version",
                    "paper_candidate requires v2 core artifacts: " + ", ".join(non_v2),
                )
            )
        if strategy_spec.get("status") not in {"research", "paper_candidate"}:
            issues.append(
                ValidationIssue(
                    "$.strategy_spec.status",
                    "paper_candidate requires a research-ready StrategySpec",
                )
            )
        if not linked_source_note_documents:
            issues.append(ValidationIssue("$.verdict_report.evidence.source_notes", "paper_candidate requires source notes"))
        for index, source_note in enumerate(linked_source_note_documents):
            if source_note.get("status") not in {"reviewed", "implemented"}:
                issues.append(
                    ValidationIssue(
                        f"$.verdict_report.evidence.source_notes[{index}]",
                        "paper_candidate requires reviewed or implemented source notes",
                    )
                )
        findings = documents.get("findings")
        if findings is None:
            issues.append(
                ValidationIssue(
                    "$.findings",
                    "paper_candidate requires independent findings with a passed research_gate",
                )
            )
        else:
            summary = findings["summary"]
            if findings["target_gate"] != "research_gate":
                issues.append(ValidationIssue("$.findings.target_gate", "must be research_gate for paper_candidate"))
            if summary["gate_result"] != "pass":
                issues.append(ValidationIssue("$.findings.summary.gate_result", "must be pass for paper_candidate"))
            reviewer = findings["reviewer"]
            owners = {owner for owner in (strategy_spec.get("owner"), receipt.get("owner")) if owner}
            if reviewer in owners:
                issues.append(ValidationIssue("$.findings.reviewer", "must be independent from strategy and run owners"))
            if verdict.get("owner") != reviewer:
                issues.append(ValidationIssue("$.verdict_report.owner", "must match the independent findings reviewer"))

        failed_gates = verdict.get("gate_results", {}).get("failed_gates", [])
        if failed_gates:
            issues.append(ValidationIssue("$.verdict_report.gate_results.failed_gates", "must be empty for paper_candidate"))
        if adapter is None or adapter.get("mode") not in {"research", "paper"}:
            issues.append(ValidationIssue("$.adapter.mode", "paper_candidate requires a research or paper adapter"))
        if not is_finite_number(costs.get("gross_pnl")) or not is_finite_number(costs.get("net_pnl")):
            issues.append(ValidationIssue("$.cost_waterfall", "paper_candidate requires numeric gross_pnl and net_pnl"))
        cost_components = costs.get("costs", {})
        required_costs = ("fees", "spread", "slippage")
        if not isinstance(cost_components, dict) or any(
            not is_finite_number(cost_components.get(field)) or cost_components[field] < 0
            for field in required_costs
        ):
            issues.append(
                ValidationIssue(
                    "$.cost_waterfall.costs",
                    "paper_candidate requires non-negative numeric fees, spread, and slippage",
                )
            )
        elif is_finite_number(costs.get("gross_pnl")) and is_finite_number(costs.get("net_pnl")):
            numeric_costs = [value for value in cost_components.values() if is_finite_number(value)]
            expected_net = costs["gross_pnl"] - sum(numeric_costs)
            if not math.isclose(costs["net_pnl"], expected_net, rel_tol=1e-9, abs_tol=1e-12):
                issues.append(
                    ValidationIssue(
                        "$.cost_waterfall.net_pnl",
                        "must equal gross_pnl minus numeric cost components",
                    )
                )
        cost_assumptions = costs.get("assumptions", {})
        required_assumptions = ("fee_model", "fill_model", "latency_model", "depth_model")
        if not isinstance(cost_assumptions, dict) or any(
            not isinstance(cost_assumptions.get(field), str)
            or not cost_assumptions[field].strip()
            or cost_assumptions[field].strip().lower() in {"none", "n/a", "not applicable"}
            for field in required_assumptions
        ):
            issues.append(
                ValidationIssue(
                    "$.cost_waterfall.assumptions",
                    "paper_candidate requires explicit fee, fill, latency, and depth assumptions",
                )
            )
        required_promotion_metrics = (
            "pnl",
            "total_return",
            "sharpe",
            "max_drawdown",
            "turnover",
            "expectancy",
        )
        for metric_group in ("gross_metrics", "net_metrics"):
            values = metrics.get(metric_group, {})
            missing_metrics = [
                metric_name
                for metric_name in required_promotion_metrics
                if not isinstance(values, dict) or not is_finite_number(values.get(metric_name))
            ]
            if missing_metrics:
                issues.append(
                    ValidationIssue(
                        f"$.metrics_report.{metric_group}",
                        "paper_candidate requires numeric " + ", ".join(missing_metrics),
                    )
                )
        robustness = metrics.get("robustness", {})
        baseline_result = robustness.get("null_baseline_result") if isinstance(robustness, dict) else None
        if not isinstance(baseline_result, str) or not baseline_result.strip():
            issues.append(
                ValidationIssue(
                    "$.metrics_report.robustness.null_baseline_result",
                    "paper_candidate verdicts require a recorded null/random baseline result",
                )
            )
        elif baseline_result.strip().lower().startswith(("not applicable", "n/a", "none")):
            issues.append(
                ValidationIssue(
                    "$.metrics_report.robustness.null_baseline_result",
                    "paper_candidate requires a null or random baseline result",
                )
            )
        trades = sample.get("trades") if isinstance(sample, dict) else None
        if not isinstance(trades, int) or isinstance(trades, bool) or trades < 1:
            issues.append(ValidationIssue("$.metrics_report.sample.trades", "paper_candidate requires at least one trade"))
        if (
            not isinstance(sample, dict)
            or sample.get("evaluation_scope") not in {"out_of_sample", "walk_forward"}
            or not sample.get("holdout_start_time")
            or not sample.get("holdout_end_time")
        ):
            issues.append(
                ValidationIssue(
                    "$.metrics_report.sample",
                    "paper_candidate requires an explicit out-of-sample or walk-forward holdout window",
                )
            )
        else:
            holdout_interval = require_ordered_interval(
                sample.get("holdout_start_time"),
                sample.get("holdout_end_time"),
                "$.metrics_report.sample.holdout",
                issues,
            )
            if sample_interval and holdout_interval and (
                holdout_interval[0] < sample_interval[0] or holdout_interval[1] > sample_interval[1]
            ):
                issues.append(
                    ValidationIssue(
                        "$.metrics_report.sample.holdout",
                        "holdout window must be contained by the sample window",
                    )
                )
        if not isinstance(robustness, dict) or not any(
            is_finite_number(robustness.get(field)) for field in ("dsr_or_psr", "pbo")
        ):
            issues.append(
                ValidationIssue(
                    "$.metrics_report.robustness",
                    "paper_candidate requires numeric DSR/PSR or PBO evidence",
                )
            )
        if not isinstance(robustness, dict) or not robustness.get("stress_results"):
            issues.append(
                ValidationIssue(
                    "$.metrics_report.robustness.stress_results",
                    "paper_candidate requires stress-test results",
                )
            )
        parameter_stability = robustness.get("parameter_stability") if isinstance(robustness, dict) else None
        if (
            not isinstance(parameter_stability, str)
            or not parameter_stability.strip()
            or parameter_stability.strip().lower().startswith(("not applicable", "n/a", "none"))
        ):
            issues.append(
                ValidationIssue(
                    "$.metrics_report.robustness.parameter_stability",
                    "paper_candidate requires parameter-stability evidence",
                )
            )
        execution = strategy_spec.get("execution", {})
        required_execution = ("order_type", "fill_model", "latency_assumption_ms", "fee_model", "slippage_model")
        if not isinstance(execution, dict) or any(
            field not in execution or execution[field] in (None, "") for field in required_execution
        ) or execution.get("order_type") == "diagnostic_only" or any(
            isinstance(execution.get(field), str)
            and execution[field].strip().lower() in {"none", "n/a", "not applicable"}
            for field in ("fill_model", "fee_model", "slippage_model")
        ):
            issues.append(
                ValidationIssue(
                    "$.strategy_spec.execution",
                    "paper_candidate requires explicit order, fill, latency, fee, and slippage assumptions",
                )
            )
        validation_plan = strategy_spec.get("validation", {})
        if not isinstance(validation_plan, dict) or any(
            not isinstance(validation_plan.get(field), str)
            or not validation_plan[field].strip()
            or validation_plan[field].strip().lower().startswith(("not applicable", "n/a", "none"))
            for field in ("train_test_split", "holdout_policy")
        ):
            issues.append(
                ValidationIssue(
                    "$.strategy_spec.validation",
                    "paper_candidate requires explicit train/test split and holdout policy",
                )
            )
        windows = validation_plan.get("windows") if isinstance(validation_plan, dict) else None
        if not isinstance(windows, dict):
            issues.append(
                ValidationIssue(
                    "$.strategy_spec.validation.windows",
                    "paper_candidate requires explicit train, validation, and holdout windows",
                )
            )
        else:
            train = require_ordered_interval(
                windows.get("train_start"), windows.get("train_end"), "$.strategy_spec.validation.windows.train", issues
            )
            validation = require_ordered_interval(
                windows.get("validation_start"),
                windows.get("validation_end"),
                "$.strategy_spec.validation.windows.validation",
                issues,
            )
            holdout = require_ordered_interval(
                windows.get("holdout_start"),
                windows.get("holdout_end"),
                "$.strategy_spec.validation.windows.holdout",
                issues,
            )
            if train and validation and holdout and not (
                train[1] <= validation[0] and validation[1] <= holdout[0]
            ):
                issues.append(
                    ValidationIssue(
                        "$.strategy_spec.validation.windows",
                        "train, validation, and holdout windows must be ordered and non-overlapping",
                    )
                )
            if holdout and (
                holdout[0] != parse_timestamp(sample.get("holdout_start_time"))
                or holdout[1] != parse_timestamp(sample.get("holdout_end_time"))
            ):
                issues.append(
                    ValidationIssue(
                        "$.strategy_spec.validation.windows.holdout",
                        "must match the metrics holdout window",
                    )
                )
        fingerprint = data_manifest.get("fingerprint", {})
        if fingerprint.get("method") != "sha256" or not isinstance(fingerprint.get("value"), str):
            issues.append(ValidationIssue("$.data_manifest.fingerprint", "paper_candidate requires a SHA-256 fingerprint"))

        for metric_field, cost_field in (("pnl", "gross_pnl"),):
            if (
                is_finite_number(metrics.get("gross_metrics", {}).get(metric_field))
                and is_finite_number(costs.get(cost_field))
                and not math.isclose(
                metrics["gross_metrics"][metric_field], costs.get(cost_field), rel_tol=1e-9, abs_tol=1e-12
                )
            ):
                issues.append(
                    ValidationIssue(
                        "$.metrics_report.gross_metrics.pnl",
                        "must equal cost_waterfall.gross_pnl",
                    )
                )
        if (
            is_finite_number(metrics.get("net_metrics", {}).get("pnl"))
            and is_finite_number(costs.get("net_pnl"))
            and not math.isclose(
                metrics["net_metrics"]["pnl"], costs.get("net_pnl"), rel_tol=1e-9, abs_tol=1e-12
            )
        ):
            issues.append(
                ValidationIssue(
                    "$.metrics_report.net_metrics.pnl",
                    "must equal cost_waterfall.net_pnl",
                )
            )

    return ValidationResult(not issues, issues, "package")

"""Artifact and package validation for The Pass."""

from __future__ import annotations

import hashlib
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
from .candidate_contract import candidate_assembly_manifest

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
ARTIFACT_SCHEMAS["agent_task"] = {1: "agent_task.schema.json"}
ARTIFACT_SCHEMAS["agent_result"] = {1: "agent_result.schema.json"}
ARTIFACT_SCHEMAS["agent_run"] = {1: "agent_run.schema.json"}
ARTIFACT_SCHEMAS["dataset_plan"] = {1: "dataset_plan.v1.schema.json"}
ARTIFACT_SCHEMAS["dataset_receipt"] = {
    1: "dataset_receipt.v1.schema.json",
    2: "dataset_receipt.v2.schema.json",
}
ARTIFACT_SCHEMAS["reproduction_spec"] = {
    1: "reproduction_spec.v1.schema.json",
    2: "reproduction_spec.v2.schema.json",
}
ARTIFACT_SCHEMAS["reviewer_attestation"] = {
    1: "reviewer_attestation.v1.schema.json",
    2: "reviewer_attestation.v2.schema.json",
}
ARTIFACT_SCHEMAS["reviewer_key_registry"] = {
    1: "reviewer_key_registry.v1.schema.json"
}
ARTIFACT_SCHEMAS["robustness_report"] = {
    2: "robustness_report.v2.schema.json"
}
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
PACKAGE_EVIDENCE_ARTIFACTS = (
    "audit_report",
    "robustness_report",
    "instrument_registry",
    "quality_report",
    "feature_manifest",
    "screen_report",
    "paper_plan",
    "observation_manifest",
    "divergence_report",
    "risk_policy",
    "risk_report",
    "automation_run",
    "incident_report",
    "config_diff",
    "approval_pack",
    "reproduction_spec",
)
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
        if (candidate / ".codex-plugin" / "plugin.json").exists() and (
            candidate / "schemas"
        ).exists():
            return candidate
    return Path.cwd().resolve()


def default_schema_dir() -> Path:
    repo_root = repo_root_from(Path(__file__).resolve())
    repo_schemas = repo_root / "schemas"
    plugin_manifest = repo_root / ".codex-plugin" / "plugin.json"
    try:
        plugin = json.loads(plugin_manifest.read_text(encoding="utf-8"))
        if (
            isinstance(plugin, dict)
            and plugin.get("name") == "the-pass"
            and repo_schemas.is_dir()
        ):
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


def load_schema(
    schema_dir: Path, artifact_type: str, schema_version: int
) -> dict[str, Any]:
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
    if {
        "status",
        "proposed_name",
        "source_notes",
        "edge",
        "market",
        "test",
        "risks",
        "kill_when",
        "blockers",
    } <= keys:
        return "hypothesis"
    if {
        "market",
        "edge",
        "data",
        "signal",
        "execution",
        "risk",
        "validation",
        "gates",
    } <= keys:
        return "strategy_spec"
    if {
        "dataset_name",
        "source",
        "coverage",
        "schema",
        "quality",
        "fingerprint",
    } <= keys:
        return "data_manifest"
    if {"strategy_spec", "code_version", "data_manifest", "outputs", "safety"} <= keys:
        return "run_receipt"
    if {"sample", "gross_metrics", "net_metrics", "robustness"} <= keys:
        return "metrics_report"
    if {
        "source_package_id",
        "registration",
        "matrix",
        "cells",
        "statistics",
        "validation",
        "promotion_eligible",
        "report_fingerprint",
    } <= keys:
        return "robustness_report"
    if {"gross_pnl", "costs", "net_pnl", "assumptions"} <= keys:
        return "cost_waterfall"
    if {"verdict", "gate_results", "evidence", "risks", "next_action"} <= keys:
        return "verdict_report"
    if {
        "strategy_spec",
        "mode",
        "sample",
        "variants",
        "baseline",
        "costs",
        "results",
        "decision",
        "safety",
    } <= keys:
        return "screen_report"
    if {"package", "reviewer", "target_gate", "findings", "summary"} <= keys:
        return "findings"
    if {
        "source_finding",
        "package",
        "target_gate",
        "scope",
        "fix_plan",
        "result",
    } <= keys:
        return "refire_ticket"
    if {"target_gate", "package", "budget", "laps", "final"} <= keys:
        return "simmer_laps"
    if {
        "source_package",
        "strategy_spec",
        "adapter",
        "config_hash",
        "observation",
        "decision_logic",
        "divergence_policy",
        "safety",
        "status",
    } <= keys:
        return "paper_plan"
    if {
        "paper_plan",
        "source_package",
        "data_capture",
        "signals",
        "simulated_orders",
        "quality",
    } <= keys:
        return "observation_manifest"
    if {
        "paper_plan",
        "observation_manifest",
        "sample",
        "comparisons",
        "breaches",
        "decision",
    } <= keys:
        return "divergence_report"
    if {
        "strategy_id",
        "requested_gate",
        "config_hash",
        "adapter",
        "evidence",
        "risk_limits",
        "operations",
        "human_decisions_required",
        "status",
    } <= keys:
        return "approval_pack"
    if {"ledger", "filters", "summary", "packages", "status"} <= keys:
        return "receipt_summary"
    if {
        "gate_id",
        "gate_result",
        "policy_version",
        "policy_hash",
        "package_id",
        "evidence",
        "reviewer",
    } <= keys:
        return "gate_decision"
    if {
        "topic",
        "objective",
        "sources",
        "hypotheses",
        "evidence_gaps",
        "next_tests",
        "status",
    } <= keys:
        return "research_brief"
    if {"target", "reviewer", "findings", "verdict", "evidence", "limitations"} <= keys:
        return "audit_report"
    if {
        "source",
        "venue",
        "asset_class",
        "instrument_id",
        "event_type",
        "event_time_ns",
        "receive_time_ns",
        "ingest_id",
        "payload",
    } <= keys:
        return "canonical_event"
    if {"registry_id", "instruments", "fingerprint"} <= keys:
        return "instrument_registry"
    if {"dataset_id", "checks", "summary", "quarantine", "promotion_impact"} <= keys:
        return "quality_report"
    if {
        "dataset_fingerprint",
        "code_version",
        "config_hash",
        "features",
        "output_fingerprint",
    } <= keys:
        return "feature_manifest"
    if {
        "policy_id",
        "policy_version",
        "asset_class",
        "sizing",
        "limits",
        "stress",
        "policy_hash",
    } <= keys:
        return "risk_policy"
    if {
        "package_id",
        "policy_id",
        "policy_hash",
        "drawdown_distribution",
        "expected_shortfall",
        "scenario_losses",
        "verdict",
    } <= keys:
        return "risk_report"
    if {
        "caller_provider",
        "target_provider",
        "role",
        "objective",
        "workspace_root",
        "mode",
        "timeout_seconds",
        "max_output_bytes",
        "forbidden_actions",
    } <= keys:
        return "agent_task"
    if {
        "task_id",
        "status",
        "summary",
        "findings",
        "changed_paths",
        "next_actions",
        "assumptions",
        "issues",
    } <= keys:
        return "agent_result"
    if {
        "run_id",
        "task_id",
        "task_fingerprint",
        "caller_provider",
        "target_provider",
        "provider",
        "execution",
        "streams",
        "result_fingerprint",
        "patch",
    } <= keys:
        return "agent_run"
    if {
        "owner",
        "trigger",
        "command",
        "inputs",
        "allowed_writes",
        "forbidden_actions",
        "timeout_seconds",
        "retry_policy",
        "alert_sink",
        "freeze_procedure",
    } <= keys:
        return "automation_spec"
    if {
        "automation_spec",
        "idempotency_key",
        "started_at",
        "finished_at",
        "attempts",
        "status",
        "outputs",
        "receipt",
    } <= keys:
        return "automation_run"
    if {
        "severity",
        "detected_at",
        "source",
        "summary",
        "timeline",
        "impact",
        "evidence",
        "actions",
        "status",
    } <= keys:
        return "incident_report"
    if {
        "venue",
        "account_scope",
        "adapter",
        "config_hash",
        "decision",
        "accepted_live_capability_adr",
        "grants_live_approval",
    } <= keys:
        return "human_decision"
    if {
        "before_hash",
        "after_hash",
        "changes",
        "review_required",
        "secrets_present",
    } <= keys:
        return "config_diff"
    if {
        "gateway",
        "config_hash",
        "intent_fingerprint",
        "external_side_effects",
        "transport_available",
        "result",
    } <= keys:
        return "dry_run_proof"
    if {
        "account_equity",
        "micro_notional_cap",
        "daily_loss_cap",
        "max_leverage",
        "freeze_conditions",
        "policy_hash",
    } <= keys:
        return "live_risk_contract"
    return None


def validate_workflow_artifact(
    artifact_type: str, document: dict[str, Any]
) -> list[ValidationIssue]:
    """Check workflow invariants that are awkward or unclear in JSON Schema."""

    issues: list[ValidationIssue] = []

    if artifact_type == "run_receipt":
        lineage_fields = (
            "supersedes_package_id",
            "supersedes_artifacts_hash",
        )
        if sum(field in document for field in lineage_fields) == 1:
            issues.append(
                ValidationIssue(
                    "$",
                    "successor run receipt requires both supersedes lineage fields",
                )
            )

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

    if artifact_type == "robustness_report":
        from .robustness import (
            cscv_pbo,
            deflated_sharpe_ratio,
            probabilistic_sharpe_ratio,
            reality_check,
        )
        from .data.contracts import stable_fingerprint

        registration = document["registration"]
        registration_fingerprint = registration.get("registration_fingerprint")
        registration_core = {
            key: value
            for key, value in registration.items()
            if key != "registration_fingerprint"
        }
        if registration_fingerprint != stable_fingerprint(registration_core):
            issues.append(
                ValidationIssue(
                    "$.registration.registration_fingerprint",
                    "does not match the registered experiment inputs",
                )
            )

        expected_report_fingerprint = stable_fingerprint(
            {
                key: value
                for key, value in document.items()
                if key != "report_fingerprint"
            }
        )
        if document["report_fingerprint"] != expected_report_fingerprint:
            issues.append(
                ValidationIssue(
                    "$.report_fingerprint",
                    "does not match the robustness report contents",
                )
            )

        matrix = document["matrix"]
        variants = registration["variants"]
        selected_index = registration["selected_index"]
        folds = document["validation"]["folds"]
        cells = document["cells"]
        if selected_index >= len(variants):
            issues.append(
                ValidationIssue(
                    "$.registration.selected_index",
                    "must identify a registered variant",
                )
            )
        null_index = document["null_baseline"]["variant_index"]
        if null_index >= len(variants) or null_index == selected_index:
            issues.append(
                ValidationIssue(
                    "$.null_baseline.variant_index",
                    "must identify a registered variant distinct from the selected variant",
                )
            )
        if len(matrix) != len(folds):
            issues.append(
                ValidationIssue("$.matrix", "must contain one row per validation fold")
            )
        if any(len(row) != len(variants) for row in matrix):
            issues.append(
                ValidationIssue("$.matrix", "must contain one column per registered variant")
            )
        expected_cells = len(matrix) * len(variants)
        if len(cells) != expected_cells:
            issues.append(
                ValidationIssue(
                    "$.cells", "must contain exactly one cell per fold and variant"
                )
            )
        observed_keys: set[tuple[int, int]] = set()
        for index, cell in enumerate(cells):
            if not isinstance(cell, dict):
                continue
            key = (cell["fold_id"], cell["variant_index"])
            if key in observed_keys:
                issues.append(
                    ValidationIssue(
                        f"$.cells[{index}]",
                        "duplicates a fold and variant cell",
                    )
                )
                continue
            observed_keys.add(key)
            fold_id, variant_index = key
            if not (
                0 <= fold_id < len(matrix)
                and 0 <= variant_index < len(variants)
            ):
                issues.append(
                    ValidationIssue(
                        f"$.cells[{index}]",
                        "fold_id or variant_index is outside the registered matrix",
                    )
                )
                continue
            matrix_value = matrix[fold_id][variant_index]
            cell_value = cell["net_return"]
            if matrix_value is None:
                matches = cell["status"] == "failed" and cell_value is None
            else:
                matches = (
                    cell["status"] == "complete"
                    and is_finite_number(cell_value)
                    and math.isclose(
                        cell_value,
                        matrix_value,
                        rel_tol=1e-12,
                        abs_tol=1e-15,
                    )
                )
            if not matches:
                issues.append(
                    ValidationIssue(
                        f"$.cells[{index}]",
                        "must match the status and return in the registered matrix",
                    )
                )
        if document["validation"]["mode"] == "purged_walk_forward":
            for index, fold in enumerate(folds):
                if fold["id"] != index:
                    issues.append(
                        ValidationIssue(
                            f"$.validation.folds[{index}].id",
                            "fold IDs must be contiguous and match matrix row order",
                        )
                    )
                if not (
                    fold["train_start"] < fold["train_end"] <= fold["test_start"]
                    < fold["test_end"]
                ):
                    issues.append(
                        ValidationIssue(
                            f"$.validation.folds[{index}]",
                            "train and test intervals must be ordered and non-overlapping",
                        )
                    )
                train = set(range(fold["train_start"], fold["train_end"]))
                test = set(range(fold["test_start"], fold["test_end"]))
                expected_purged = list(
                    range(
                        max(
                            fold["train_end"],
                            fold["test_start"]
                            - document["validation"]["purge_observations"],
                        ),
                        fold["test_start"],
                    )
                )
                expected_embargoed = list(
                    range(
                        fold["test_end"],
                        fold["test_end"]
                        + document["validation"]["embargo_observations"],
                    )
                )
                observed_embargoed = fold["embargoed"]
                embargo_matches = (
                    observed_embargoed == expected_embargoed
                    if index < len(folds) - 1
                    else observed_embargoed
                    == expected_embargoed[: len(observed_embargoed)]
                    and len(observed_embargoed)
                    <= document["validation"]["embargo_observations"]
                )
                purged = set(fold["purged"])
                embargoed = set(observed_embargoed)
                if (
                    fold["purged"] != expected_purged
                    or not embargo_matches
                    or train & test
                    or train & purged
                    or train & embargoed
                    or test & purged
                    or test & embargoed
                    or purged & embargoed
                ):
                    issues.append(
                        ValidationIssue(
                            f"$.validation.folds[{index}]",
                            "purge and embargo indices must exactly match the registered non-overlapping policy",
                        )
                    )
                if index and fold["test_start"] < (
                    folds[index - 1]["test_end"]
                    + len(folds[index - 1]["embargoed"])
                ):
                    issues.append(
                        ValidationIssue(
                            f"$.validation.folds[{index}].test_start",
                            "test folds must advance beyond the prior test and embargo",
                        )
                    )
        holdout = require_ordered_interval(
            document["validation"]["holdout_start_time"],
            document["validation"]["holdout_end_time"],
            "$.validation.holdout",
            issues,
        )
        if holdout is None:
            issues.append(
                ValidationIssue(
                    "$.validation.holdout",
                    "robustness holdout must be an ordered RFC3339 interval",
                )
            )
        failed_cells = sum(
            1 for cell in cells if isinstance(cell, dict) and cell.get("status") != "complete"
        )
        if document["failed_cells"] != failed_cells:
            issues.append(
                ValidationIssue(
                    "$.failed_cells", "must equal the number of non-complete cells"
                )
            )

        if not issues and failed_cells == 0:
            complete_matrix = [[float(value) for value in row] for row in matrix]
            selected = [row[selected_index] for row in complete_matrix]
            baseline = [row[null_index] for row in complete_matrix]
            selected_mean = sum(selected) / len(selected)
            baseline_mean = sum(baseline) / len(baseline)
            if (
                not math.isclose(
                    document["null_baseline"]["selected_mean_return"],
                    selected_mean,
                    rel_tol=1e-12,
                    abs_tol=1e-15,
                )
                or not math.isclose(
                    document["null_baseline"]["baseline_mean_return"],
                    baseline_mean,
                    rel_tol=1e-12,
                    abs_tol=1e-15,
                )
                or document["null_baseline"]["status"]
                != ("pass" if selected_mean > baseline_mean else "blocked")
            ):
                issues.append(
                    ValidationIssue(
                        "$.null_baseline",
                        "must be derived from selected and preregistered null returns",
                    )
                )
            expected_neighbors = [
                index
                for index in (selected_index - 1, selected_index + 1)
                if 0 <= index < len(variants) and index != null_index
            ]
            neighbor_means = [
                sum(row[index] for row in complete_matrix) / len(complete_matrix)
                for index in expected_neighbors
            ]
            worst_neighbor = min(neighbor_means) if neighbor_means else None
            stability = document["parameter_stability"]
            observed_worst = stability["worst_neighbor_return"]
            worst_matches = (
                worst_neighbor is None
                and observed_worst is None
                or is_finite_number(observed_worst)
                and worst_neighbor is not None
                and math.isclose(
                    observed_worst,
                    worst_neighbor,
                    rel_tol=1e-12,
                    abs_tol=1e-15,
                )
            )
            expected_stability = (
                "pass"
                if expected_neighbors
                and worst_neighbor is not None
                and worst_neighbor > 0
                else "blocked"
            )
            if (
                stability["neighbor_indices"] != expected_neighbors
                or not worst_matches
                or stability["status"] != expected_stability
            ):
                issues.append(
                    ValidationIssue(
                        "$.parameter_stability",
                        "must be derived from registered neighboring variants",
                    )
                )
            trial_sharpes = []
            for column in range(len(variants)):
                values = [row[column] for row in complete_matrix]
                average = sum(values) / len(values)
                variance = sum((value - average) ** 2 for value in values) / max(
                    1, len(values) - 1
                )
                trial_sharpes.append(average / variance**0.5 if variance else 0.0)
            blocks = document["validation"]["cscv_blocks"]
            expected_statistics = {
                "pbo": cscv_pbo(complete_matrix, blocks=blocks),
                "psr": probabilistic_sharpe_ratio(selected),
                "dsr": deflated_sharpe_ratio(
                    selected, trial_sharpes=trial_sharpes
                ),
                "reality_check": reality_check(
                    complete_matrix, bootstrap_samples=500, seed=7
                ),
            }
            for field, expected in expected_statistics.items():
                observed = document["statistics"].get(field)
                if isinstance(expected, dict):
                    if observed != expected:
                        issues.append(
                            ValidationIssue(
                                f"$.statistics.{field}",
                                "does not match recomputation from the registered matrix",
                            )
                        )
                elif not is_finite_number(observed) or not math.isclose(
                    observed, expected, rel_tol=1e-12, abs_tol=1e-15
                ):
                    issues.append(
                        ValidationIssue(
                            f"$.statistics.{field}",
                            "does not match recomputation from the registered matrix",
                        )
                    )

        mandatory_stress = {
            "fees_x1_5",
            "slippage_x2",
            "latency_x2",
            "depth_x0_5",
            "depth_x0_25",
            "maker_fill_probability_x0_5",
            "funding_worst_decile",
            "exchange_outage",
            "missing_interval",
            "correlated_gap",
            "forced_deleverage",
        }
        stress_names = {
            row["scenario"] for row in document["stress_results"]
        }
        if len(stress_names) != len(document["stress_results"]):
            issues.append(
                ValidationIssue(
                    "$.stress_results",
                    "stress scenario names must be unique",
                )
            )
        promotion_conditions = (
            document["status"] == "complete"
            and failed_cells == 0
            and isinstance(document["source_package_id"], str)
            and document["validation"]["mode"] == "purged_walk_forward"
            and document["null_baseline"]["status"] == "pass"
            and document["parameter_stability"]["status"] == "pass"
            and bool(document["stress_results"])
            and mandatory_stress <= stress_names
            and all(row["status"] == "pass" for row in document["stress_results"])
            and all(
                cell.get("runtime_promotion_eligible") is True
                for cell in cells
                if isinstance(cell, dict)
            )
        )
        if document["promotion_eligible"] != promotion_conditions:
            issues.append(
                ValidationIssue(
                    "$.promotion_eligible",
                    "must be derived from complete purged walk-forward, runtime, baseline, stress, and stability evidence",
                )
            )

    if artifact_type == "screen_report":
        decision = document["decision"]
        if (
            decision["status"] == "backtest_candidate"
            and not document["variants"]["tried"]
        ):
            issues.append(
                ValidationIssue(
                    "$.variants.tried", "must record at least one tried variant"
                )
            )

    if artifact_type == "findings":
        summary = document["summary"]
        blocking = [
            finding
            for finding in document["findings"]
            if finding["blocks_promotion"]
            and finding["status"] in {"open", "confirmed"}
        ]
        if summary["gate_result"] == "pass" and blocking:
            issues.append(
                ValidationIssue(
                    "$.summary.gate_result",
                    "cannot pass with unresolved blocking findings",
                )
            )

    if artifact_type == "simmer_laps":
        if len(document["laps"]) > document["budget"]["max_laps"]:
            issues.append(ValidationIssue("$.laps", "cannot exceed budget.max_laps"))
        lap_numbers = [lap["lap"] for lap in document["laps"]]
        if lap_numbers != list(range(1, len(lap_numbers) + 1)):
            issues.append(
                ValidationIssue(
                    "$.laps", "lap numbers must be contiguous and start at 1"
                )
            )
        movement = [lap["moved_gate"] for lap in document["laps"]]
        if document["final"]["status"] == "passed" and not any(movement):
            issues.append(
                ValidationIssue(
                    "$.final.status", "cannot pass when no lap moved the target gate"
                )
            )
        if any(
            not movement[index] and not movement[index + 1]
            for index in range(len(movement) - 1)
        ):
            issues.append(
                ValidationIssue(
                    "$.laps", "must stop after two consecutive no-progress laps"
                )
            )

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
        blocking_breaches = [
            breach for breach in document["breaches"] if breach["blocks_promotion"]
        ]
        if (
            document["decision"]["status"] == "risk_review_candidate"
            and blocking_breaches
        ):
            issues.append(
                ValidationIssue(
                    "$.decision.status",
                    "cannot be risk_review_candidate while a blocking divergence breach exists",
                )
            )

    if artifact_type == "receipt_summary":
        if document["summary"]["entries"] != len(document["packages"]):
            issues.append(
                ValidationIssue(
                    "$.summary.entries", "must equal the number of package rows"
                )
            )

    return issues


def is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def normalize_identity(value: Any) -> str:
    """Compare human reviewer/owner identifiers without whitespace or case bypasses."""

    return value.strip().casefold() if isinstance(value, str) else ""


def validate_agent_run_artifact(
    document: dict[str, Any], schema_dir: Path, artifact_path: Path
) -> list[ValidationIssue]:
    """Validate the embedded result and receipt-level consistency."""

    issues: list[ValidationIssue] = []
    if document["caller_provider"] == document["target_provider"]:
        issues.append(
            ValidationIssue("$.target_provider", "must differ from caller_provider")
        )
    expected_cwd = (
        "source_read_only" if document["mode"] == "read_only" else "detached_worktree"
    )
    if document["execution"]["cwd_strategy"] != expected_cwd:
        issues.append(
            ValidationIssue(
                "$.execution.cwd_strategy", f"must be {expected_cwd} for {document['mode']}"
            )
        )
    try:
        started = datetime.fromisoformat(
            document["execution"]["started_at"].replace("Z", "+00:00")
        )
        finished = datetime.fromisoformat(
            document["execution"]["finished_at"].replace("Z", "+00:00")
        )
        if started > finished:
            issues.append(
                ValidationIssue("$.execution.finished_at", "must not precede started_at")
            )
    except (TypeError, ValueError):
        pass
    if (
        document["status"] in {"complete", "blocked"}
        and document["execution"]["exit_code"] != 0
    ):
        issues.append(
            ValidationIssue(
                "$.execution.exit_code", "must be zero for complete or blocked runs"
            )
        )
    selection = document["model_selection"]
    current_policy_path = Path(__file__).resolve().parent / "policies" / "agent-orchestration.v1.yaml"
    if current_policy_path.is_file():
        current_policy = yaml.safe_load(current_policy_path.read_text(encoding="utf-8"))
        current_policy_sha256 = hashlib.sha256(
            json.dumps(
                current_policy,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
        if document["policy"]["sha256"] == current_policy_sha256:
            routing = current_policy["model_routing"]
            routing_sha256 = hashlib.sha256(
                json.dumps(
                    routing,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                ).encode("utf-8")
            ).hexdigest()
            if selection["routing_policy_sha256"] != routing_sha256:
                issues.append(
                    ValidationIssue(
                        "$.model_selection.routing_policy_sha256",
                        "must fingerprint the routing section of the recorded policy",
                    )
                )
            entry = routing["providers"][document["target_provider"]][
                selection["resolved_profile"]
            ]
            expected_effort = (
                entry["critical_effort"]
                if selection["resolved_workload_class"] == "critical"
                else entry["effort"]
            )
            expected_capabilities = sorted(set(entry["capabilities"]))
            if selection["requested_model"] != entry["model"]:
                issues.append(
                    ValidationIssue(
                        "$.model_selection.requested_model",
                        "must match the recorded policy profile",
                    )
                )
            if selection["reasoning_effort"] != expected_effort:
                issues.append(
                    ValidationIssue(
                        "$.model_selection.reasoning_effort",
                        "must match the recorded policy profile",
                    )
                )
            if selection["capabilities"] != expected_capabilities:
                issues.append(
                    ValidationIssue(
                        "$.model_selection.capabilities",
                        "must match the recorded policy profile",
                    )
                )
    argv = document["execution"]["sanitized_argv"]
    model_positions = [index for index, value in enumerate(argv) if value == "--model"]
    valid_model_position = (
        len(model_positions) == 1 and model_positions[0] + 1 < len(argv)
    )
    provider_started = document["execution"]["exit_code"] is not None
    if provider_started and not valid_model_position:
        issues.append(
            ValidationIssue("$.execution.sanitized_argv", "must contain one model selection")
        )
    elif valid_model_position and argv[model_positions[0] + 1] != selection["requested_model"]:
        issues.append(
            ValidationIssue(
                "$.model_selection.requested_model",
                "must match the model in sanitized_argv",
            )
        )
    effort = selection["reasoning_effort"]
    if valid_model_position and document["target_provider"] == "claude":
        effort_positions = [index for index, value in enumerate(argv) if value == "--effort"]
        if effort is None and effort_positions:
            issues.append(
                ValidationIssue(
                    "$.model_selection.reasoning_effort",
                    "must be null when Claude argv has no effort override",
                )
            )
        elif effort is not None and (
            len(effort_positions) != 1
            or effort_positions[0] + 1 >= len(argv)
            or argv[effort_positions[0] + 1] != effort
        ):
            issues.append(
                ValidationIssue(
                    "$.model_selection.reasoning_effort",
                    "must match the Claude effort in sanitized_argv",
                )
            )
    elif valid_model_position:
        expected_effort = f'model_reasoning_effort="{effort}"'
        if effort is None or expected_effort not in argv:
            issues.append(
                ValidationIssue(
                    "$.model_selection.reasoning_effort",
                    "must match the Codex reasoning config in sanitized_argv",
                )
            )
    result = document["result"]
    fingerprint = document["result_fingerprint"]
    if result is None:
        if document["status"] in {"complete", "blocked"}:
            issues.append(
                ValidationIssue("$.result", "is required for complete or blocked runs")
            )
        if fingerprint is not None:
            issues.append(
                ValidationIssue("$.result_fingerprint", "must be null when result is null")
            )
    else:
        result_schema = load_schema(schema_dir, "agent_result", 1)
        validator = Draft202012Validator(result_schema, format_checker=FORMAT_CHECKER)
        for error in sorted(
            validator.iter_errors(result), key=lambda item: list(item.absolute_path)
        ):
            path = schema_path(error)
            suffix = path[1:] if path.startswith("$") else f".{path}"
            issues.append(ValidationIssue(f"$.result{suffix}", error.message))
        if result.get("task_id") != document["task_id"]:
            issues.append(
                ValidationIssue("$.result.task_id", "must match the run task_id")
            )
        expected_status = {
            "complete": "complete",
            "blocked": "blocked",
        }.get(document["status"])
        if expected_status is not None and result.get("status") != expected_status:
            issues.append(
                ValidationIssue("$.result.status", "must match the run status")
            )
        payload = json.dumps(
            result, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        expected_fingerprint = hashlib.sha256(payload).hexdigest()
        if fingerprint != expected_fingerprint:
            issues.append(
                ValidationIssue(
                    "$.result_fingerprint", "must fingerprint the embedded result"
                )
            )

    patch = document["patch"]
    if document["mode"] == "read_only" and patch is not None:
        issues.append(ValidationIssue("$.patch", "must be null for read_only runs"))
    if patch is not None:
        if result is None:
            issues.append(ValidationIssue("$.patch", "requires an embedded result"))
        elif patch["changed_paths"] != result["changed_paths"]:
            issues.append(
                ValidationIssue(
                    "$.patch.changed_paths", "must equal result.changed_paths"
                )
            )
        patch_path = Path(patch["path"])
        if not patch_path.is_absolute():
            issues.append(ValidationIssue("$.patch.path", "must be an absolute path"))
        elif (
            patch_path.name != f"agent-patch-{document['run_id']}.patch"
            or patch_path.parent.resolve() != artifact_path.parent.resolve()
        ):
            issues.append(
                ValidationIssue(
                    "$.patch.path", "must use the run ID beside the agent_run receipt"
                )
            )
        elif patch_path.is_symlink() or not patch_path.is_file():
            issues.append(
                ValidationIssue("$.patch.path", "must identify an existing regular file")
            )
        else:
            digest = hashlib.sha256()
            total = 0
            maximum = document["limits"]["max_output_bytes"]
            try:
                with patch_path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        total += len(chunk)
                        if total > maximum:
                            issues.append(
                                ValidationIssue(
                                    "$.patch.path", "patch exceeds the recorded output limit"
                                )
                            )
                            break
                        digest.update(chunk)
            except OSError as exc:
                issues.append(
                    ValidationIssue("$.patch.path", f"cannot read patch evidence: {exc}")
                )
            else:
                if total <= maximum and digest.hexdigest() != patch["sha256"]:
                    issues.append(
                        ValidationIssue(
                            "$.patch.sha256", "must fingerprint the current patch bytes"
                        )
                    )
    elif (
        result is not None
        and document["status"] in {"complete", "blocked"}
        and document["mode"] == "worktree_patch"
        and result["changed_paths"]
    ):
        issues.append(
            ValidationIssue("$.patch", "is required when a worktree run changed files")
        )
    return issues


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
        return ValidationResult(
            False, [ValidationIssue(str(artifact_path), str(exc))], artifact_type
        )

    if not isinstance(document, dict):
        return ValidationResult(
            False,
            [
                ValidationIssue(
                    str(artifact_path), "artifact document must be an object"
                )
            ],
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
            [
                ValidationIssue(
                    str(artifact_path), f"unknown artifact type: {detected_type}"
                )
            ],
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
        return ValidationResult(
            False, [ValidationIssue(str(artifact_path), str(exc))], detected_type
        )

    validator = Draft202012Validator(schema, format_checker=FORMAT_CHECKER)
    for error in sorted(
        validator.iter_errors(document), key=lambda item: list(item.absolute_path)
    ):
        issues.append(ValidationIssue(schema_path(error), error.message))

    if not issues:
        if detected_type == "adapter":
            for issue in validate_adapter_contract(document):
                issues.append(
                    ValidationIssue(issue.path, issue.message, issue.severity)
                )
        elif detected_type in {
            "run_receipt",
            "metrics_report",
            "robustness_report",
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
        elif detected_type == "agent_run":
            issues.extend(validate_agent_run_artifact(document, schema_dir, artifact_path))

    schema_id = schema.get("$id")
    return ValidationResult(
        not issues,
        issues,
        detected_type,
        schema_id if isinstance(schema_id, str) else None,
    )


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
        issues.append(
            ValidationIssue(issue_path, f"must reference {expected_path.name}")
        )


def require_false_flag(
    document: dict[str, Any], section: str, field: str, issues: list[ValidationIssue]
) -> None:
    section_value = document.get(section)
    if not isinstance(section_value, dict) or section_value.get(field) is not False:
        issues.append(ValidationIssue(f"$.{section}.{field}", "must be false"))


def parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or RFC3339_DATETIME.fullmatch(value) is None:
        return None
    try:
        return datetime.fromisoformat(
            value.replace("Z", "+00:00").replace("z", "+00:00")
        )
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
        issues.append(
            ValidationIssue(path, "must contain RFC 3339 start and end timestamps")
        )
        return None
    if parsed_start >= parsed_end:
        issues.append(ValidationIssue(path, "start must be earlier than end"))
        return None
    return parsed_start, parsed_end


def package_evidence_paths(package_dir: Path) -> list[tuple[str, Path]]:
    """Return promotion-relevant package-root artifacts excluded only for governance decisions."""

    package_dir = package_dir.resolve()
    evidence: list[tuple[str, Path]] = []
    for artifact_type in PACKAGE_EVIDENCE_ARTIFACTS:
        candidates: set[Path] = set()
        for extension in ARTIFACT_EXTENSIONS:
            canonical = package_dir / f"{artifact_type}{extension}"
            if canonical.is_file():
                candidates.add(canonical)
            if artifact_type == "audit_report":
                candidates.update(
                    path
                    for path in package_dir.glob(f"audit_report.*{extension}")
                    if path.is_file()
                )
        by_stem: dict[str, list[Path]] = {}
        for candidate in candidates:
            by_stem.setdefault(candidate.stem, []).append(candidate)
        ambiguous = [paths for paths in by_stem.values() if len(paths) > 1]
        if ambiguous:
            names = ", ".join(
                sorted(path.name for paths in ambiguous for path in paths)
            )
            raise ArtifactValidationError(
                f"ambiguous promotion artifact {artifact_type}: {names}"
            )
        for candidate in sorted(candidates):
            try:
                resolved = candidate.resolve()
                resolved.relative_to(package_dir)
            except ValueError as exc:
                raise ArtifactValidationError(
                    f"package evidence escapes package directory: {candidate}"
                ) from exc
            evidence.append((artifact_type, resolved))
    return evidence


def validate_package(
    package_dir: Path, *, schema_dir: Path | None = None
) -> ValidationResult:
    package_dir = package_dir.resolve()
    schema_dir = (schema_dir or default_schema_dir()).resolve()
    issues: list[ValidationIssue] = []

    if not package_dir.exists() or not package_dir.is_dir():
        return ValidationResult(
            False,
            [ValidationIssue(str(package_dir), "package directory does not exist")],
            "package",
        )

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
                    f"ambiguous artifact {artifact_type}: "
                    + ", ".join(path.name for path in matches),
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
        result = validate_artifact(
            path, schema_dir=schema_dir, artifact_type=artifact_type
        )
        issues.extend(
            ValidationIssue(f"{path.name}:{issue.path}", issue.message)
            for issue in result.issues
        )
        if result.ok:
            loaded = load_document(path)
            if isinstance(loaded, dict):
                documents[artifact_type] = loaded

    try:
        promotion_evidence = package_evidence_paths(package_dir)
    except ArtifactValidationError as exc:
        issues.append(ValidationIssue(str(package_dir), str(exc)))
        promotion_evidence = []
    promotion_documents: dict[str, dict[str, Any]] = {}
    for artifact_type, path in promotion_evidence:
        result = validate_artifact(
            path, schema_dir=schema_dir, artifact_type=artifact_type
        )
        issues.extend(
            ValidationIssue(f"{path.name}:{issue.path}", issue.message)
            for issue in result.issues
        )
        if result.ok and artifact_type not in promotion_documents:
            loaded = load_document(path)
            if isinstance(loaded, dict):
                promotion_documents[artifact_type] = loaded

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
    if (
        sample_interval
        and coverage_interval
        and (
            sample_interval[0] < coverage_interval[0]
            or sample_interval[1] > coverage_interval[1]
        )
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

    for field in (
        "live_trading_enabled",
        "real_order_path_available",
        "credentials_available",
    ):
        require_false_flag(receipt, "safety", field, issues)

    for artifact_type, document in (
        ("metrics_report", metrics),
        ("cost_waterfall", costs),
        ("verdict_report", verdict),
    ):
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
            issues.append(
                ValidationIssue(
                    "$.verdict_report.evidence.source_notes", "must be an array"
                )
            )
        else:
            for index, source_note in enumerate(source_notes):
                source_note_path = resolve_package_link(package_dir, source_note)
                if source_note_path is None or not link_exists(
                    package_dir, source_note
                ):
                    issues.append(
                        ValidationIssue(
                            f"$.verdict_report.evidence.source_notes[{index}]",
                            "linked source note does not exist",
                        )
                    )
                    continue
                source_result = validate_artifact(
                    source_note_path, schema_dir=schema_dir, artifact_type="source_note"
                )
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
            for field in (
                "live_trading_enabled",
                "real_order_path_available",
                "credentials_required",
            ):
                if adapter_safety.get(field) is not False:
                    issues.append(
                        ValidationIssue(
                            f"$.adapter.safety.{field}",
                            "must be false for public packages",
                        )
                    )

        if (
            adapter.get("mode") == "diagnostic"
            and verdict.get("verdict") == "paper_candidate"
        ):
            issues.append(
                ValidationIssue(
                    "$.verdict_report.verdict",
                    "diagnostic adapters cannot produce paper_candidate verdicts",
                )
            )

    if verdict.get("verdict") == "paper_candidate":
        robustness_report = promotion_documents.get("robustness_report")
        if robustness_report is None:
            issues.append(
                ValidationIssue(
                    "$.robustness_report",
                    "paper_candidate requires a validated robustness_report.v2 artifact",
                )
            )
        else:
            source_package_id = receipt.get("supersedes_package_id")
            if (
                source_package_id is not None
                and robustness_report.get("source_package_id") != source_package_id
            ):
                issues.append(
                    ValidationIssue(
                        "$.robustness_report.source_package_id",
                        "must match run_receipt.supersedes_package_id",
                    )
                )
            expected_assembly = candidate_assembly_manifest(
                strategy=strategy_spec,
                metrics=metrics,
                verdict=verdict,
                robustness=robustness_report,
                findings=documents.get("findings", {}),
            )
            if receipt.get("candidate_assembly") != expected_assembly:
                issues.append(
                    ValidationIssue(
                        "$.run_receipt.candidate_assembly",
                        "must match the deterministic candidate assembly contract",
                    )
                )
            if robustness_report.get("promotion_eligible") is not True:
                issues.append(
                    ValidationIssue(
                        "$.robustness_report.promotion_eligible",
                        "paper_candidate requires promotion-eligible robustness evidence",
                    )
                )
            robustness_evidence = verdict.get("evidence", {}).get(
                "robustness_report"
            )
            robustness_path = next(
                (
                    path
                    for artifact_type, path in promotion_evidence
                    if artifact_type == "robustness_report"
                ),
                None,
            )
            if (
                robustness_path is None
                or robustness_evidence != robustness_path.name
            ):
                issues.append(
                    ValidationIssue(
                        "$.verdict_report.evidence.robustness_report",
                        "must reference the exact robustness_report artifact",
                    )
                )
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
            issues.append(
                ValidationIssue(
                    "$.verdict_report.evidence.source_notes",
                    "paper_candidate requires source notes",
                )
            )
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
                issues.append(
                    ValidationIssue(
                        "$.findings.target_gate",
                        "must be research_gate for paper_candidate",
                    )
                )
            if summary["gate_result"] != "pass":
                issues.append(
                    ValidationIssue(
                        "$.findings.summary.gate_result",
                        "must be pass for paper_candidate",
                    )
                )
            reviewer = findings["reviewer"]
            normalized_reviewer = normalize_identity(reviewer)
            owners = {
                normalize_identity(owner)
                for owner in (strategy_spec.get("owner"), receipt.get("owner"))
                if normalize_identity(owner)
            }
            if normalized_reviewer in owners:
                issues.append(
                    ValidationIssue(
                        "$.findings.reviewer",
                        "must be independent from strategy and run owners",
                    )
                )
            if normalize_identity(verdict.get("owner")) != normalized_reviewer:
                issues.append(
                    ValidationIssue(
                        "$.verdict_report.owner",
                        "must match the independent findings reviewer",
                    )
                )

        failed_gates = verdict.get("gate_results", {}).get("failed_gates", [])
        if failed_gates:
            issues.append(
                ValidationIssue(
                    "$.verdict_report.gate_results.failed_gates",
                    "must be empty for paper_candidate",
                )
            )
        if adapter is None or adapter.get("mode") not in {"research", "paper"}:
            issues.append(
                ValidationIssue(
                    "$.adapter.mode",
                    "paper_candidate requires a research or paper adapter",
                )
            )
        if not is_finite_number(costs.get("gross_pnl")) or not is_finite_number(
            costs.get("net_pnl")
        ):
            issues.append(
                ValidationIssue(
                    "$.cost_waterfall",
                    "paper_candidate requires numeric gross_pnl and net_pnl",
                )
            )
        cost_components = costs.get("costs", {})
        required_costs = ("fees", "spread", "slippage")
        if not isinstance(cost_components, dict) or any(
            not is_finite_number(cost_components.get(field))
            or cost_components[field] < 0
            for field in required_costs
        ):
            issues.append(
                ValidationIssue(
                    "$.cost_waterfall.costs",
                    "paper_candidate requires non-negative numeric fees, spread, and slippage",
                )
            )
        elif is_finite_number(costs.get("gross_pnl")) and is_finite_number(
            costs.get("net_pnl")
        ):
            numeric_costs = [
                value for value in cost_components.values() if is_finite_number(value)
            ]
            expected_net = costs["gross_pnl"] - sum(numeric_costs)
            if not math.isclose(
                costs["net_pnl"], expected_net, rel_tol=1e-9, abs_tol=1e-12
            ):
                issues.append(
                    ValidationIssue(
                        "$.cost_waterfall.net_pnl",
                        "must equal gross_pnl minus numeric cost components",
                    )
                )
        cost_assumptions = costs.get("assumptions", {})
        required_assumptions = (
            "fee_model",
            "fill_model",
            "latency_model",
            "depth_model",
        )
        if not isinstance(cost_assumptions, dict) or any(
            not isinstance(cost_assumptions.get(field), str)
            or not cost_assumptions[field].strip()
            or cost_assumptions[field].strip().lower()
            in {"none", "n/a", "not applicable"}
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
        annualization = metrics.get("annualization")
        if (
            not isinstance(annualization, dict)
            or not is_finite_number(annualization.get("periods_per_year"))
            or annualization["periods_per_year"] <= 0
            or not isinstance(annualization.get("method"), str)
            or not annualization["method"].strip()
        ):
            issues.append(
                ValidationIssue(
                    "$.metrics_report.annualization",
                    "paper_candidate requires an explicit positive annualization policy",
                )
            )
        for metric_group in ("gross_metrics", "net_metrics"):
            values = metrics.get(metric_group, {})
            missing_metrics = [
                metric_name
                for metric_name in required_promotion_metrics
                if not isinstance(values, dict)
                or not is_finite_number(values.get(metric_name))
            ]
            if missing_metrics:
                issues.append(
                    ValidationIssue(
                        f"$.metrics_report.{metric_group}",
                        "paper_candidate requires numeric "
                        + ", ".join(missing_metrics),
                    )
                )
        robustness = metrics.get("robustness", {})
        baseline_result = (
            robustness.get("null_baseline_result")
            if isinstance(robustness, dict)
            else None
        )
        if not isinstance(baseline_result, str) or not baseline_result.strip():
            issues.append(
                ValidationIssue(
                    "$.metrics_report.robustness.null_baseline_result",
                    "paper_candidate verdicts require a recorded null/random baseline result",
                )
            )
        elif (
            baseline_result.strip()
            .lower()
            .startswith(("not applicable", "n/a", "none"))
        ):
            issues.append(
                ValidationIssue(
                    "$.metrics_report.robustness.null_baseline_result",
                    "paper_candidate requires a null or random baseline result",
                )
            )
        trades = sample.get("trades") if isinstance(sample, dict) else None
        if not isinstance(trades, int) or isinstance(trades, bool) or trades < 1:
            issues.append(
                ValidationIssue(
                    "$.metrics_report.sample.trades",
                    "paper_candidate requires at least one trade",
                )
            )
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
            if (
                sample_interval
                and holdout_interval
                and (
                    holdout_interval[0] < sample_interval[0]
                    or holdout_interval[1] > sample_interval[1]
                )
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
        parameter_stability = (
            robustness.get("parameter_stability")
            if isinstance(robustness, dict)
            else None
        )
        if (
            not isinstance(parameter_stability, str)
            or not parameter_stability.strip()
            or parameter_stability.strip()
            .lower()
            .startswith(("not applicable", "n/a", "none"))
        ):
            issues.append(
                ValidationIssue(
                    "$.metrics_report.robustness.parameter_stability",
                    "paper_candidate requires parameter-stability evidence",
                )
            )
        if robustness_report is not None and isinstance(robustness, dict):
            expected_robustness = {
                "null_baseline_result": robustness_report["null_baseline"][
                    "summary"
                ],
                "dsr_or_psr": robustness_report["statistics"]["dsr"],
                "pbo": robustness_report["statistics"]["pbo"]["pbo"],
                "stress_results": [
                    row["summary"] for row in robustness_report["stress_results"]
                ],
                "parameter_stability": robustness_report[
                    "parameter_stability"
                ]["summary"],
            }
            for field, expected in expected_robustness.items():
                observed = robustness.get(field)
                if isinstance(expected, float):
                    matches = is_finite_number(observed) and math.isclose(
                        observed, expected, rel_tol=1e-12, abs_tol=1e-15
                    )
                else:
                    matches = observed == expected
                if not matches:
                    issues.append(
                        ValidationIssue(
                            f"$.metrics_report.robustness.{field}",
                            "must be derived from the exact robustness_report",
                        )
                    )
            validation_evidence = robustness_report["validation"]
            if (
                sample.get("evaluation_scope") != "walk_forward"
                or sample.get("holdout_start_time")
                != validation_evidence["holdout_start_time"]
                or sample.get("holdout_end_time")
                != validation_evidence["holdout_end_time"]
            ):
                issues.append(
                    ValidationIssue(
                        "$.metrics_report.sample",
                        "walk-forward scope and holdout must match robustness_report",
                    )
                )
        execution = strategy_spec.get("execution", {})
        required_execution = (
            "order_type",
            "fill_model",
            "latency_assumption_ms",
            "fee_model",
            "slippage_model",
        )
        if (
            not isinstance(execution, dict)
            or any(
                field not in execution or execution[field] in (None, "")
                for field in required_execution
            )
            or execution.get("order_type") == "diagnostic_only"
            or any(
                isinstance(execution.get(field), str)
                and execution[field].strip().lower()
                in {"none", "n/a", "not applicable"}
                for field in ("fill_model", "fee_model", "slippage_model")
            )
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
            or validation_plan[field]
            .strip()
            .lower()
            .startswith(("not applicable", "n/a", "none"))
            for field in ("train_test_split", "holdout_policy")
        ):
            issues.append(
                ValidationIssue(
                    "$.strategy_spec.validation",
                    "paper_candidate requires explicit train/test split and holdout policy",
                )
            )
        windows = (
            validation_plan.get("windows")
            if isinstance(validation_plan, dict)
            else None
        )
        if not isinstance(windows, dict):
            issues.append(
                ValidationIssue(
                    "$.strategy_spec.validation.windows",
                    "paper_candidate requires explicit train, validation, and holdout windows",
                )
            )
        else:
            train = require_ordered_interval(
                windows.get("train_start"),
                windows.get("train_end"),
                "$.strategy_spec.validation.windows.train",
                issues,
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
            if (
                train
                and validation
                and holdout
                and not (train[1] <= validation[0] and validation[1] <= holdout[0])
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
        if fingerprint.get("method") != "sha256" or not isinstance(
            fingerprint.get("value"), str
        ):
            issues.append(
                ValidationIssue(
                    "$.data_manifest.fingerprint",
                    "paper_candidate requires a SHA-256 fingerprint",
                )
            )

        for metric_field, cost_field in (("pnl", "gross_pnl"),):
            if (
                is_finite_number(metrics.get("gross_metrics", {}).get(metric_field))
                and is_finite_number(costs.get(cost_field))
                and not math.isclose(
                    metrics["gross_metrics"][metric_field],
                    costs.get(cost_field),
                    rel_tol=1e-9,
                    abs_tol=1e-12,
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
                metrics["net_metrics"]["pnl"],
                costs.get("net_pnl"),
                rel_tol=1e-9,
                abs_tol=1e-12,
            )
        ):
            issues.append(
                ValidationIssue(
                    "$.metrics_report.net_metrics.pnl",
                    "must equal cost_waterfall.net_pnl",
                )
            )

    return ValidationResult(not issues, issues, "package")

"""Artifact and package validation for The Pass."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from .adapter_contract import validate_adapter_contract

ARTIFACT_TYPES = {
    "adapter": "adapter.schema.json",
    "source_note": "source_note.schema.json",
    "strategy_spec": "strategy_spec.schema.json",
    "data_manifest": "data_manifest.schema.json",
    "run_receipt": "run_receipt.schema.json",
    "metrics_report": "metrics_report.schema.json",
    "cost_waterfall": "cost_waterfall.schema.json",
    "verdict_report": "verdict_report.schema.json",
}

PACKAGE_CORE_ARTIFACTS = (
    "strategy_spec",
    "data_manifest",
    "run_receipt",
    "metrics_report",
    "cost_waterfall",
    "verdict_report",
)

PACKAGE_OPTIONAL_ARTIFACTS = ("adapter", "source_note")
ARTIFACT_EXTENSIONS = (".json", ".yaml", ".yml")


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
    return repo_root_from(Path(__file__).resolve()) / "schemas"


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


def load_schema(schema_dir: Path, artifact_type: str) -> dict[str, Any]:
    schema_name = ARTIFACT_TYPES.get(artifact_type)
    if schema_name is None:
        raise ArtifactValidationError(f"unknown artifact type: {artifact_type}")
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
    return None


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

    try:
        schema = load_schema(schema_dir, detected_type)
    except ArtifactValidationError as exc:
        return ValidationResult(False, [ValidationIssue(str(artifact_path), str(exc))], detected_type)

    validator = Draft202012Validator(schema)
    for error in sorted(validator.iter_errors(document), key=lambda item: list(item.absolute_path)):
        issues.append(ValidationIssue(schema_path(error), error.message))

    if detected_type == "adapter" and not issues:
        for issue in validate_adapter_contract(document):
            issues.append(ValidationIssue(issue.path, issue.message, issue.severity))

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


def require_false_flag(document: dict[str, Any], section: str, field: str, issues: list[ValidationIssue]) -> None:
    section_value = document.get(section)
    if not isinstance(section_value, dict) or section_value.get(field) is not False:
        issues.append(ValidationIssue(f"$.{section}.{field}", "must be false"))


def validate_package(package_dir: Path, *, schema_dir: Path | None = None) -> ValidationResult:
    package_dir = package_dir.resolve()
    schema_dir = (schema_dir or default_schema_dir()).resolve()
    issues: list[ValidationIssue] = []

    if not package_dir.exists() or not package_dir.is_dir():
        return ValidationResult(False, [ValidationIssue(str(package_dir), "package directory does not exist")], "package")

    artifact_paths: dict[str, Path] = {}
    for artifact_type in (*PACKAGE_CORE_ARTIFACTS, *PACKAGE_OPTIONAL_ARTIFACTS):
        path = find_artifact(package_dir, artifact_type)
        if path is not None:
            artifact_paths[artifact_type] = path

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
    metrics = documents["metrics_report"]
    costs = documents["cost_waterfall"]
    verdict = documents["verdict_report"]

    if not link_exists(package_dir, receipt.get("strategy_spec")):
        issues.append(ValidationIssue("$.run_receipt.strategy_spec", "linked StrategySpec does not exist"))
    if not link_exists(package_dir, receipt.get("data_manifest")):
        issues.append(ValidationIssue("$.run_receipt.data_manifest", "linked data manifest does not exist"))

    outputs = receipt.get("outputs")
    if not isinstance(outputs, dict):
        issues.append(ValidationIssue("$.run_receipt.outputs", "must be an object"))
    else:
        expected_outputs = {
            "metrics_report": "metrics_report",
            "cost_waterfall": "cost_waterfall",
            "verdict_report": "verdict_report",
        }
        for output_field in expected_outputs:
            if not link_exists(package_dir, outputs.get(output_field)):
                issues.append(
                    ValidationIssue(
                        f"$.run_receipt.outputs.{output_field}",
                        "linked output artifact does not exist",
                    )
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

    evidence = verdict.get("evidence")
    if not isinstance(evidence, dict):
        issues.append(ValidationIssue("$.verdict_report.evidence", "must be an object"))
    else:
        for field in ("metrics_report", "cost_waterfall", "data_manifest"):
            if not link_exists(package_dir, evidence.get(field)):
                issues.append(ValidationIssue(f"$.verdict_report.evidence.{field}", "linked evidence does not exist"))
        source_notes = evidence.get("source_notes", [])
        if not isinstance(source_notes, list):
            issues.append(ValidationIssue("$.verdict_report.evidence.source_notes", "must be an array"))
        else:
            for index, source_note in enumerate(source_notes):
                if not link_exists(package_dir, source_note):
                    issues.append(
                        ValidationIssue(
                            f"$.verdict_report.evidence.source_notes[{index}]",
                            "linked source note does not exist",
                        )
                    )

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

    return ValidationResult(not issues, issues, "package")

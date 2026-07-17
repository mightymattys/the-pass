"""Single-artifact validation entry point."""

from __future__ import annotations

from pathlib import Path

from jsonschema import Draft202012Validator

from ..adapter_contract import validate_adapter_contract
from .artifacts import validate_workflow_artifact
from .common import schema_path
from .detection import detect_artifact_type
from .models import ArtifactValidationError, FORMAT_CHECKER, ValidationIssue, ValidationResult
from .receipts import validate_agent_run_artifact
from .registry import ARTIFACT_TYPES, default_schema_dir, load_document, load_schema

def validate_artifact(
    artifact_path: Path,
    *,
    schema_dir: Path | None = None,
    artifact_type: str | None = None,
    ledger_path: Path | None = None,
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
            issues.extend(
                validate_workflow_artifact(
                    detected_type,
                    document,
                    ledger_path=ledger_path,
                    artifact_path=artifact_path,
                )
            )
        elif detected_type == "agent_run":
            issues.extend(validate_agent_run_artifact(document, schema_dir, artifact_path))

    schema_id = schema.get("$id")
    return ValidationResult(
        not any(issue.severity == "error" for issue in issues),
        issues,
        detected_type,
        schema_id if isinstance(schema_id, str) else None,
    )


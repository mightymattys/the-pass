"""Package validation and promotion rules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import (
    link_exists,
    package_evidence_paths,
    require_exact_artifact_link,
    require_false_flag,
    require_ordered_interval,
    resolve_package_link,
)
from .core import validate_artifact
from .models import ArtifactValidationError, ValidationIssue, ValidationResult
from .paper_candidate import validate_paper_candidate
from .registry import (
    ARTIFACT_EXTENSIONS,
    PACKAGE_CORE_ARTIFACTS,
    PACKAGE_OPTIONAL_ARTIFACTS,
    default_schema_dir,
    load_document,
)

def validate_package(
    package_dir: Path,
    *,
    schema_dir: Path | None = None,
    ledger_path: Path | None = None,
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
            path,
            schema_dir=schema_dir,
            artifact_type=artifact_type,
            ledger_path=ledger_path,
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
            path,
            schema_dir=schema_dir,
            artifact_type=artifact_type,
            ledger_path=ledger_path,
        )
        issues.extend(
            ValidationIssue(f"{path.name}:{issue.path}", issue.message)
            for issue in result.issues
        )
        if result.ok and artifact_type not in promotion_documents:
            loaded = load_document(path)
            if isinstance(loaded, dict):
                promotion_documents[artifact_type] = loaded

    if any(issue.severity == "error" for issue in issues):
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
        validate_paper_candidate(
            promotion_documents=promotion_documents,
            issues=issues,
            receipt=receipt,
            strategy_spec=strategy_spec,
            metrics=metrics,
            verdict=verdict,
            documents=documents,
            promotion_evidence=promotion_evidence,
            linked_source_note_documents=linked_source_note_documents,
            adapter=adapter,
            costs=costs,
            sample=sample,
            sample_interval=sample_interval,
            data_manifest=data_manifest,
        )

    return ValidationResult(
        not any(issue.severity == "error" for issue in issues),
        issues,
        "package",
    )

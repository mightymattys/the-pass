"""Artifact schema registry and schema/document loading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .models import ArtifactValidationError

_V1_V2_ARTIFACTS = (
    "adapter", "source_note", "hypothesis", "strategy_spec", "data_manifest",
    "run_receipt", "metrics_report", "cost_waterfall", "verdict_report",
    "screen_report", "findings", "refire_ticket", "simmer_laps", "paper_plan",
    "observation_manifest", "divergence_report", "approval_pack", "receipt_summary",
)

ARTIFACT_SCHEMAS = {
    artifact_type: {1: f"{artifact_type}.schema.json", 2: f"{artifact_type}.v2.schema.json"}
    for artifact_type in _V1_V2_ARTIFACTS
}
ARTIFACT_SCHEMAS.update({
    "gate_decision": {2: "gate_decision.v2.schema.json"},
    "research_brief": {2: "research_brief.v2.schema.json"},
    "audit_report": {2: "audit_report.v2.schema.json"},
    "canonical_event": {2: "canonical_event.v2.schema.json"},
    "instrument_registry": {2: "instrument_registry.v2.schema.json"},
    "quality_report": {2: "quality_report.v2.schema.json"},
    "feature_manifest": {2: "feature_manifest.v2.schema.json"},
    "risk_policy": {2: "risk_policy.v2.schema.json"},
    "risk_report": {2: "risk_report.v2.schema.json"},
    "automation_spec": {2: "automation_spec.v2.schema.json"},
    "automation_run": {2: "automation_run.v2.schema.json"},
    "incident_report": {2: "incident_report.v2.schema.json"},
    "human_decision": {2: "human_decision.v2.schema.json"},
    "config_diff": {2: "config_diff.v2.schema.json"},
    "dry_run_proof": {2: "dry_run_proof.v2.schema.json"},
    "live_risk_contract": {2: "live_risk_contract.v2.schema.json"},
    "agent_task": {1: "agent_task.schema.json"},
    "agent_result": {1: "agent_result.schema.json"},
    "agent_run": {1: "agent_run.schema.json"},
    "dataset_plan": {1: "dataset_plan.v1.schema.json"},
    "dataset_receipt": {2: "dataset_receipt.v2.schema.json"},
    "reproduction_spec": {1: "reproduction_spec.v1.schema.json", 2: "reproduction_spec.v2.schema.json"},
    "reviewer_attestation": {1: "reviewer_attestation.v1.schema.json", 2: "reviewer_attestation.v2.schema.json"},
    "reviewer_key_registry": {1: "reviewer_key_registry.v1.schema.json"},
    "robustness_report": {2: "robustness_report.v2.schema.json", 3: "robustness_report.v3.schema.json"},
})
ARTIFACT_TYPES = {
    artifact_type: versions[max(versions)]
    for artifact_type, versions in ARTIFACT_SCHEMAS.items()
}

PACKAGE_CORE_ARTIFACTS = (
    "strategy_spec", "data_manifest", "run_receipt", "metrics_report",
    "cost_waterfall", "verdict_report",
)
PACKAGE_OPTIONAL_ARTIFACTS = ("adapter", "source_note", "findings")
PACKAGE_EVIDENCE_ARTIFACTS = (
    "audit_report", "robustness_report", "instrument_registry", "quality_report",
    "feature_manifest", "screen_report", "paper_plan", "observation_manifest",
    "divergence_report", "risk_policy", "risk_report", "automation_run",
    "incident_report", "config_diff", "approval_pack", "reproduction_spec",
)
ARTIFACT_EXTENSIONS = (".json", ".yaml", ".yml")


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
    module_file = Path(__file__).resolve().parent.parent / "validator.py"
    return schema_dir_from(module_file)


def schema_dir_from(module_file: Path) -> Path:
    """Resolve schemas using the compatibility module's location."""

    repo_root = repo_root_from(module_file)
    repo_schemas = repo_root / "schemas"
    plugin_manifest = repo_root / ".codex-plugin" / "plugin.json"
    try:
        plugin = json.loads(plugin_manifest.read_text(encoding="utf-8"))
        if isinstance(plugin, dict) and plugin.get("name") == "the-pass" and repo_schemas.is_dir():
            return repo_schemas
    except (OSError, UnicodeError, json.JSONDecodeError):
        pass
    return module_file.resolve().parent / "schemas"


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

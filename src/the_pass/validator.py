"""Compatibility facade for :mod:`the_pass.validators`."""

from pathlib import Path

from .validators.models import (
    ArtifactValidationError,
    FORMAT_CHECKER,
    RFC3339_DATETIME,
    ValidationIssue,
    ValidationResult,
)
from .validators.registry import (
    ARTIFACT_EXTENSIONS,
    ARTIFACT_SCHEMAS,
    ARTIFACT_TYPES,
    PACKAGE_CORE_ARTIFACTS,
    PACKAGE_EVIDENCE_ARTIFACTS,
    PACKAGE_OPTIONAL_ARTIFACTS,
    load_document,
    load_schema,
    repo_root_from,
    schema_dir_from as _schema_dir_from,
)
from .validators.common import (
    find_artifact,
    is_finite_number,
    link_exists,
    normalize_identity,
    package_evidence_paths,
    parse_timestamp,
    require_exact_artifact_link,
    require_false_flag,
    require_ordered_interval,
    resolve_package_link,
    schema_path,
)
from .validators.detection import detect_artifact_type
from .validators.artifacts import validate_workflow_artifact
from .validators.receipts import validate_agent_run_artifact
from .validators.robustness import validate_robustness_report_v3
from .validators.core import validate_artifact
from .validators.promotion import validate_package


def default_schema_dir() -> Path:
    return _schema_dir_from(Path(__file__))

__all__ = (
    "ARTIFACT_EXTENSIONS", "ARTIFACT_SCHEMAS", "ARTIFACT_TYPES",
    "ArtifactValidationError", "FORMAT_CHECKER", "PACKAGE_CORE_ARTIFACTS",
    "PACKAGE_EVIDENCE_ARTIFACTS", "PACKAGE_OPTIONAL_ARTIFACTS",
    "RFC3339_DATETIME", "ValidationIssue", "ValidationResult",
    "default_schema_dir", "detect_artifact_type", "find_artifact",
    "is_finite_number", "link_exists", "load_document", "load_schema",
    "normalize_identity", "package_evidence_paths", "parse_timestamp",
    "repo_root_from", "require_exact_artifact_link", "require_false_flag",
    "require_ordered_interval", "resolve_package_link", "schema_path",
    "validate_agent_run_artifact", "validate_artifact", "validate_package",
    "validate_robustness_report_v3", "validate_workflow_artifact",
)

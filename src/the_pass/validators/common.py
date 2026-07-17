"""Common validator helpers."""

from __future__ import annotations

import math
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema.exceptions import ValidationError

from .models import ArtifactValidationError, RFC3339_DATETIME, ValidationIssue
from .registry import ARTIFACT_EXTENSIONS, PACKAGE_EVIDENCE_ARTIFACTS

def is_finite_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def normalize_identity(value: Any) -> str:
    """Compare human reviewer/owner identifiers without whitespace or case bypasses."""

    return value.strip().casefold() if isinstance(value, str) else ""

def schema_path(error: ValidationError) -> str:
    if not error.absolute_path:
        return "$"
    return "$." + ".".join(str(part) for part in error.absolute_path)

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


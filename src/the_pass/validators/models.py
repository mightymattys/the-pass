"""Shared validator result types and RFC 3339 format checking."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from jsonschema import FormatChecker

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


"""Robustness reproduction-evidence binding checks."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..data.contracts import stable_fingerprint
from .models import ArtifactValidationError, ValidationIssue
from .registry import load_document


def validate_evidence_binding(
    document: dict[str, Any],
    artifact_path: Path | None,
    registration: dict[str, Any],
    expected_statistics: dict[str, Any],
    cells: list[dict[str, Any]],
    selected_oos_returns: list[float],
    issues: list[ValidationIssue],
) -> bool:
    evidence_binding = document.get("evidence_binding")
    reproduction_binding_valid = False
    if artifact_path is not None:
        reproduction_path = artifact_path.resolve().parent / "reproduction_report.json"
        try:
            reproduction = load_document(reproduction_path)
        except ArtifactValidationError:
            reproduction = None
        if isinstance(reproduction, dict) and reproduction.get("status") == "pass":
            binding = reproduction.get("robustness_binding")
            if isinstance(binding, dict):
                binding_core = {
                    key: value
                    for key, value in binding.items()
                    if key != "binding_fingerprint"
                }
                reproduction_binding_valid = (
                    binding.get("binding_grade")
                    == "reproduction_integrity_not_cell_provenance"
                    and binding.get("binding_fingerprint")
                    == stable_fingerprint(binding_core)
                    and binding.get("registration_fingerprint")
                    == registration.get("registration_fingerprint")
                    and binding.get("events_fingerprint")
                    == registration.get("events_fingerprint")
                    and binding.get("statistics_fingerprint")
                    == stable_fingerprint(expected_statistics)
                    and binding.get("cells_fingerprint")
                    == stable_fingerprint(cells)
                    and binding.get("selected_oos_returns_fingerprint")
                    == stable_fingerprint(selected_oos_returns)
                )
    evidence_binding_valid = (
        evidence_binding == "unverified_cells" and reproduction_binding_valid
    )
    if evidence_binding == "runtime_receipts":
        issues.append(
            ValidationIssue(
                "$.evidence_binding",
                "runtime_receipts is unsupported: the current strategy runtime does not persist a verifiable per-cell receipt chain",
            )
        )
    if document.get("promotion_eligible") is True and not evidence_binding_valid:
        issues.append(
            ValidationIssue(
                "$.evidence_binding",
                "promotion with unverified cells requires a passing sibling reproduction_report.json bound to the same registration, events, cells, returns, and recomputed statistics",
            )
        )
    return evidence_binding_valid

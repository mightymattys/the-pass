"""Incident artifact creation with fail-closed action vocabulary."""

from __future__ import annotations

from typing import Any, Sequence


def build_incident_report(
    *,
    incident_id: str,
    severity: str,
    detected_at: str,
    source: str,
    summary: str,
    evidence: Sequence[str],
    freeze_reason: str,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "id": incident_id,
        "severity": severity,
        "detected_at": detected_at,
        "source": source,
        "summary": summary,
        "timeline": [{"at": detected_at, "event": "detected"}, {"at": detected_at, "event": "frozen"}],
        "impact": {"promotion_blocked": True, "capital_at_risk": 0},
        "evidence": list(evidence),
        "actions": [
            {"action": "freeze", "status": "complete", "reason": freeze_reason},
            {"action": "preserve_evidence", "status": "complete"},
            {"action": "postmortem", "status": "pending"},
        ],
        "status": "contained",
    }

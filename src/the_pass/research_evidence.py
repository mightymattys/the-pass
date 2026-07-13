"""Conservative research-evidence scope reporting."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

import yaml

from .data.contracts import stable_fingerprint


def _load_object(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"expected an object: {path}")
    return document


def evidence_scope(classification: str, status: str) -> str:
    """Classify only explicit registry language; never infer full-text access."""

    normalized = classification.lower().replace("-", "_")
    if status not in {"reviewed", "implemented"} or any(
        token in normalized for token in ("backlog", "blocked")
    ):
        return "blocked"
    if "fulltext" in normalized or "full_text" in normalized:
        return "full_text"
    if "abstract" in normalized:
        return "abstract"
    if "operator" in normalized:
        return "operator_material"
    if any(token in normalized for token in ("metadata", "preview")):
        return "metadata"
    return "reviewed_unspecified"


def build_research_evidence_report(registry_path: Path) -> dict[str, Any]:
    registry_path = registry_path.resolve()
    registry = _load_object(registry_path)
    sources = registry.get("sources")
    if not isinstance(sources, list):
        raise ValueError("research registry must contain a sources array")
    repo_root = registry_path.parent.parent
    rows: list[dict[str, Any]] = []
    scopes: Counter[str] = Counter()
    categories: Counter[str] = Counter()
    ids: set[str] = set()
    for index, entry in enumerate(sources):
        if not isinstance(entry, dict):
            raise ValueError(f"registry source {index} must be an object")
        source_id = str(entry.get("id", ""))
        if not source_id or source_id in ids:
            raise ValueError(f"invalid or duplicate source id: {source_id!r}")
        ids.add(source_id)
        relative = entry.get("path")
        if not isinstance(relative, str) or not relative:
            raise ValueError(f"{source_id}: missing source-note path")
        note_path = (repo_root / relative).resolve()
        try:
            note_path.relative_to(repo_root)
        except ValueError as exc:
            raise ValueError(f"{source_id}: source path escapes repository") from exc
        note = _load_object(note_path)
        for field in ("id", "status", "evidence_classification"):
            if note.get(field) != entry.get(field):
                raise ValueError(f"{source_id}: registry and note disagree on {field}")
        classification = str(entry["evidence_classification"])
        status = str(entry["status"])
        scope = evidence_scope(classification, status)
        locator = note.get("evidence_locator")
        locator_present = isinstance(locator, str) and bool(locator.strip())
        promotion_eligible = scope == "full_text" and locator_present
        limitations = []
        if scope == "full_text" and not locator_present:
            limitations.append("full-text classification has no evidence_locator")
        if scope != "full_text":
            limitations.append(f"{scope} cannot independently support an edge claim")
        row = {
            "id": source_id,
            "category": str(entry.get("category", "uncategorized")),
            "status": status,
            "classification": classification,
            "scope": scope,
            "evidence_locator": locator if locator_present else None,
            "promotion_eligible": promotion_eligible,
            "limitations": limitations,
            "path": relative,
            "note_fingerprint": stable_fingerprint(note_path.read_text(encoding="utf-8")),
        }
        rows.append(row)
        scopes[scope] += 1
        categories[row["category"]] += 1
    eligible = sum(1 for row in rows if row["promotion_eligible"])
    report = {
        "schema_version": 1,
        "status": "ready" if eligible else "blocked",
        "registry": str(registry_path),
        "registry_fingerprint": stable_fingerprint(registry_path.read_text(encoding="utf-8")),
        "source_count": len(rows),
        "promotion_eligible_count": eligible,
        "scope_counts": dict(sorted(scopes.items())),
        "category_counts": dict(sorted(categories.items())),
        "sources": rows,
        "promotion_rule": (
            "Only explicitly full-text evidence with a locator can independently support an edge claim."
        ),
    }
    report["report_fingerprint"] = stable_fingerprint(report)
    return report

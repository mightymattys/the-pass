#!/usr/bin/env python3
"""Validate the R0 research corpus and initial StrategySpecs."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from the_pass.validator import load_document, validate_artifact  # noqa: E402


REGISTRY = ROOT / "research" / "sources.yaml"
BRIEF = ROOT / "research" / "research_brief.yaml"
OXFORD_BACKLOG = ROOT / "research" / "backlog" / "oxfordstrat-resources.yaml"
EXPECTED_SPECS = {
    "null_random_control_v1",
    "crypto_spot_buy_hold_benchmark_v1",
    "crypto_spot_time_series_momentum_v1",
    "futures_diversified_trend_v1",
    "prediction_market_complement_or_fair_value_v1",
}
MIN_STRUCTURED_SOURCES = 50
MIN_REVIEWED_SOURCES = 30
MIN_REVIEWED_OXFORD_STRATEGIES = 5


def fail(message: str) -> None:
    print(f"research corpus validation failed: {message}", file=sys.stderr)
    raise SystemExit(1)


def require_valid(path: Path, artifact_type: str) -> dict:
    result = validate_artifact(path, artifact_type=artifact_type)
    if not result.ok:
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in result.issues)
        fail(f"{path.relative_to(ROOT)}: {details}")
    document = load_document(path)
    if not isinstance(document, dict):
        fail(f"{path.relative_to(ROOT)} must be an object")
    return document


def main() -> int:
    if not REGISTRY.is_file():
        fail("missing research/sources.yaml")
    registry = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    if not isinstance(registry, dict) or registry.get("schema_version") != 1:
        fail("sources registry must use schema_version 1")
    requirements = registry.get("required_reviewed_by_category")
    sources = registry.get("sources")
    if not isinstance(requirements, dict) or not isinstance(sources, list):
        fail("registry must define category requirements and sources")

    ids: set[str] = set()
    reviewed_categories: Counter[str] = Counter()
    for row in sources:
        if not isinstance(row, dict):
            fail("source registry rows must be objects")
        source_id = row.get("id")
        if not isinstance(source_id, str) or not source_id or source_id in ids:
            fail(f"invalid or duplicate source id: {source_id}")
        ids.add(source_id)
        relative = row.get("path")
        if not isinstance(relative, str):
            fail(f"{source_id} has no source-note path")
        path = ROOT / relative
        if not path.is_file():
            fail(f"{source_id} source note does not exist: {relative}")
        note = require_valid(path, "source_note")
        for field in ("id", "status", "category", "evidence_classification"):
            if note.get(field) != row.get(field):
                fail(f"{source_id} registry and note disagree on {field}")
        if not note.get("license_note"):
            fail(f"{source_id} has no license_note")
        if row.get("status") == "reviewed":
            reviewed_categories[str(row.get("category"))] += 1

    reviewed_count = sum(reviewed_categories.values())
    if len(sources) < MIN_STRUCTURED_SOURCES:
        fail(f"V3 requires at least {MIN_STRUCTURED_SOURCES} structured source notes")
    if reviewed_count < MIN_REVIEWED_SOURCES:
        fail(f"V3 requires at least {MIN_REVIEWED_SOURCES} reviewed source notes")
    for category, minimum in requirements.items():
        if not isinstance(minimum, int) or reviewed_categories[category] < minimum:
            fail(f"category {category} requires {minimum} reviewed notes")

    specs: set[str] = set()
    for path in sorted((ROOT / "research" / "specs").glob("*.yaml")):
        document = require_valid(path, "strategy_spec")
        if document.get("status") != "research":
            fail(f"{path.name} must be research-ready")
        specs.add(str(document.get("id")))
    if specs != EXPECTED_SPECS:
        fail(f"initial StrategySpecs must be exactly {sorted(EXPECTED_SPECS)}")

    brief = require_valid(BRIEF, "research_brief")
    if brief.get("status") != "ready" or set(brief.get("hypotheses", [])) != EXPECTED_SPECS:
        fail("research brief must be ready and reference all initial StrategySpecs")
    if not set(brief.get("sources", [])).issubset(ids):
        fail("research brief references unknown sources")

    backlog = yaml.safe_load(OXFORD_BACKLOG.read_text(encoding="utf-8"))
    if not isinstance(backlog, dict) or backlog.get("classification") != "strategy-review":
        fail("OxfordStrat backlog must be explicitly classified as strategy-review")
    if len(backlog.get("strategy_families", [])) < 5 or backlog.get("pagination_review", {}).get("pages", 0) < 1:
        fail("OxfordStrat backlog does not cover the public strategy corpus")
    reviewed_oxford = {
        row["id"]
        for row in sources
        if row.get("category") == "oxfordstrat" and row.get("status") == "reviewed"
    }
    if len(reviewed_oxford) < MIN_REVIEWED_OXFORD_STRATEGIES:
        fail(f"at least {MIN_REVIEWED_OXFORD_STRATEGIES} OxfordStrat strategies must be reviewed")

    oxford_hypotheses: set[str] = set()
    for path in sorted((ROOT / "research" / "hypotheses").glob("oxford_*.yaml")):
        document = require_valid(path, "hypothesis")
        if document.get("status") != "ready_for_spec":
            fail(f"{path.name} must be ready_for_spec")
        source_paths = document.get("source_notes", [])
        if not source_paths or not all(
            isinstance(source_path, str)
            and Path(source_path).stem in reviewed_oxford
            for source_path in source_paths
        ):
            fail(f"{path.name} must reference only reviewed OxfordStrat source notes")
        oxford_hypotheses.add(str(document.get("id")))
    if len(oxford_hypotheses) < MIN_REVIEWED_OXFORD_STRATEGIES:
        fail(f"at least {MIN_REVIEWED_OXFORD_STRATEGIES} OxfordStrat baseline hypotheses are required")

    print(
        f"research corpus validation passed: {len(sources)} structured notes, {reviewed_count} reviewed, "
        f"{len(oxford_hypotheses)} OxfordStrat hypotheses, {len(specs)} StrategySpecs"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

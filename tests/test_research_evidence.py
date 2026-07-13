from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from the_pass.research_evidence import (
    build_research_evidence_report,
    evidence_scope,
)


class ResearchEvidenceTests(unittest.TestCase):
    def test_scope_is_conservative(self) -> None:
        self.assertEqual(evidence_scope("primary_academic_fulltext", "reviewed"), "full_text")
        self.assertEqual(evidence_scope("primary_academic_abstract", "reviewed"), "abstract")
        self.assertEqual(evidence_scope("primary_academic", "reviewed"), "reviewed_unspecified")
        self.assertEqual(evidence_scope("primary_academic_fulltext", "skimmed"), "blocked")

    def test_report_requires_explicit_locator_for_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "research" / "sources").mkdir(parents=True)
            registry = {
                "schema_version": 1,
                "sources": [
                    {
                        "id": "located",
                        "category": "statistics",
                        "status": "reviewed",
                        "path": "research/sources/located.yaml",
                        "evidence_classification": "primary_academic_fulltext",
                    },
                    {
                        "id": "abstract-only",
                        "category": "statistics",
                        "status": "reviewed",
                        "path": "research/sources/abstract.yaml",
                        "evidence_classification": "primary_academic_abstract",
                    },
                ],
            }
            for source_id, classification, locator in (
                ("located", "primary_academic_fulltext", "Section 3, pp. 7-9"),
                ("abstract-only", "primary_academic_abstract", None),
            ):
                note = {
                    "id": source_id,
                    "status": "reviewed",
                    "evidence_classification": classification,
                }
                if locator:
                    note["evidence_locator"] = locator
                (root / "research" / "sources" / f"{'abstract' if source_id == 'abstract-only' else source_id}.yaml").write_text(
                    yaml.safe_dump(note, sort_keys=False), encoding="utf-8"
                )
            registry_path = root / "research" / "sources.yaml"
            registry_path.write_text(yaml.safe_dump(registry, sort_keys=False), encoding="utf-8")

            report = build_research_evidence_report(registry_path)

            self.assertEqual(report["status"], "ready")
            self.assertEqual(report["promotion_eligible_count"], 1)
            self.assertEqual(report["scope_counts"]["abstract"], 1)
            self.assertEqual(len(report["report_fingerprint"]), 64)


if __name__ == "__main__":
    unittest.main()

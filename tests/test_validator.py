from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from the_pass.ledger import (
    append_ledger_entry,
    build_ledger_entry,
    read_ledger_entries,
    verify_ledger_file,
)
from the_pass.validator import validate_artifact, validate_package


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PACKAGE = ROOT / "examples" / "synthetic-breakout" / "package"
RANDOM_BASELINE_PACKAGE = ROOT / "examples" / "synthetic-random-baseline" / "package"
EXAMPLE_PACKAGES = (EXAMPLE_PACKAGE, RANDOM_BASELINE_PACKAGE)
ADAPTER_EXAMPLES = (
    ROOT / "examples" / "adapters" / "dummy-diagnostic.yaml",
    ROOT / "examples" / "adapters" / "crypto-binance-spot-klines.yaml",
    ROOT / "examples" / "adapters" / "generic-futures-contract.yaml",
    ROOT / "examples" / "adapters" / "generic-prediction-market.yaml",
)
SCHEMA_DIR = ROOT / "schemas"


class ValidatorTests(unittest.TestCase):
    def test_synthetic_packages_validate(self) -> None:
        for package in EXAMPLE_PACKAGES:
            with self.subTest(package=package):
                result = validate_package(package, schema_dir=SCHEMA_DIR)

                self.assertTrue(result.ok, [issue.as_dict() for issue in result.issues])

    def test_single_yaml_artifact_validates_with_explicit_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "adapter.yaml"
            artifact.write_text(
                """
id: test-adapter
name: Test Adapter
mode: diagnostic
asset_classes: [synthetic]
owner: tester
providers:
  - id: synthetic
    type: synthetic
    license: public-safe
    fields: [timestamp, close]
    limitations: []
provider_review:
  license: public-safe synthetic fixture
  redistribution: fixture can be redistributed with the repository
  authentication: none
  retention: tracked fixture data only
  deterministic_replay: true
  limitations: []
engine:
  name: none
  role: fixture-only
  limitations: []
policies:
  timestamp: synthetic
  cost_model: none
  fill_model: none
  risk_model: none
  settlement: none
safety:
  live_trading_enabled: false
  real_order_path_available: false
  credentials_required: false
""".strip(),
                encoding="utf-8",
            )

            result = validate_artifact(artifact, schema_dir=SCHEMA_DIR, artifact_type="adapter")

        self.assertTrue(result.ok, [issue.as_dict() for issue in result.issues])
        self.assertEqual(result.artifact_type, "adapter")

    def test_adapter_examples_validate(self) -> None:
        for adapter in ADAPTER_EXAMPLES:
            with self.subTest(adapter=adapter):
                result = validate_artifact(adapter, schema_dir=SCHEMA_DIR, artifact_type="adapter")

                self.assertTrue(result.ok, [issue.as_dict() for issue in result.issues])

    def test_adapter_contract_blocks_missing_provider_license(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "adapter.yaml"
            artifact.write_text(
                """
id: bad-adapter
name: Bad Adapter
mode: diagnostic
asset_classes: [crypto]
owner: tester
providers:
  - id: public-feed
    type: exchange-public-market-data
    license: unknown
    fields: [timestamp, close]
    limitations: []
provider_review:
  license: unknown
  redistribution: unknown
  authentication: none
  retention: unknown
  deterministic_replay: false
  limitations: []
engine:
  name: descriptor
  role: data-only
  limitations: []
policies:
  timestamp: event timestamp only
  cost_model: diagnostic placeholder
  fill_model: diagnostic placeholder
  risk_model: no capital
  settlement: spot
safety:
  live_trading_enabled: false
  real_order_path_available: false
  credentials_required: false
""".strip(),
                encoding="utf-8",
            )

            result = validate_artifact(artifact, schema_dir=SCHEMA_DIR, artifact_type="adapter")

        self.assertFalse(result.ok)
        messages = {issue.path: issue.message for issue in result.issues}
        self.assertIn("$.providers[0].license", messages)
        self.assertIn("$.provider_review.license", messages)

    def test_package_blocks_missing_required_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "package"
            shutil.copytree(EXAMPLE_PACKAGE, package)
            (package / "metrics_report.json").unlink()

            result = validate_package(package, schema_dir=SCHEMA_DIR)

        self.assertFalse(result.ok)
        self.assertTrue(any("missing required artifact: metrics_report" in issue.message for issue in result.issues))

    def test_diagnostic_adapter_cannot_be_paper_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "package"
            shutil.copytree(EXAMPLE_PACKAGE, package)
            verdict_path = package / "verdict_report.json"
            verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
            verdict["verdict"] = "paper_candidate"
            verdict_path.write_text(json.dumps(verdict, indent=2), encoding="utf-8")

            result = validate_package(package, schema_dir=SCHEMA_DIR)

        self.assertFalse(result.ok)
        self.assertTrue(any("diagnostic adapters cannot produce paper_candidate" in issue.message for issue in result.issues))

    def test_ledger_package_id_is_deterministic_across_copies(self) -> None:
        with tempfile.TemporaryDirectory() as left_tmp, tempfile.TemporaryDirectory() as right_tmp:
            left = Path(left_tmp) / "package"
            right = Path(right_tmp) / "package"
            shutil.copytree(EXAMPLE_PACKAGE, left)
            shutil.copytree(EXAMPLE_PACKAGE, right)

            left_entry = build_ledger_entry(left, gate="research_gate", recorded_at="2026-07-09T00:00:00Z")
            right_entry = build_ledger_entry(right, gate="research_gate", recorded_at="2026-07-10T00:00:00Z")

        self.assertEqual(left_entry["package_id"], right_entry["package_id"])

    def test_append_ledger_entry_and_verify_chain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.jsonl"
            package = Path(tmp) / "package"
            shutil.copytree(EXAMPLE_PACKAGE, package)

            result = append_ledger_entry(ledger, package, gate="research_gate")
            entries = read_ledger_entries(ledger)
            issues = verify_ledger_file(ledger)

        self.assertTrue(result.appended)
        self.assertEqual(len(entries), 1)
        self.assertFalse(issues, [issue.as_dict() for issue in issues])
        self.assertEqual(entries[0]["strategy_id"], "synthetic-breakout-v0")
        self.assertEqual(entries[0]["gate"], "research_gate")
        self.assertEqual(entries[0]["verdict"], "blocked")
        self.assertEqual(entries[0]["cost_waterfall"]["path"], "cost_waterfall.json")
        self.assertEqual(entries[0]["open_blockers"], ["paper promotion blocked by diagnostic adapter mode"])

    def test_random_baseline_ledger_entry_is_killed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.jsonl"
            package = Path(tmp) / "package"
            shutil.copytree(RANDOM_BASELINE_PACKAGE, package)

            result = append_ledger_entry(ledger, package, gate="research_gate")
            entries = read_ledger_entries(ledger)
            issues = verify_ledger_file(ledger)

        self.assertTrue(result.appended)
        self.assertEqual(len(entries), 1)
        self.assertFalse(issues, [issue.as_dict() for issue in issues])
        self.assertEqual(entries[0]["strategy_id"], "synthetic-random-baseline-v0")
        self.assertEqual(entries[0]["verdict"], "kill")
        self.assertEqual(entries[0]["open_blockers"], ["no edge thesis", "negative net result after illustrative costs"])

    def test_append_ledger_entry_is_idempotent_for_same_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.jsonl"
            package = Path(tmp) / "package"
            shutil.copytree(EXAMPLE_PACKAGE, package)

            first = append_ledger_entry(ledger, package, gate="research_gate")
            second = append_ledger_entry(ledger, package, gate="research_gate")
            entries = read_ledger_entries(ledger)

        self.assertTrue(first.appended)
        self.assertFalse(second.appended)
        self.assertEqual(len(entries), 1)
        self.assertEqual(first.entry["package_id"], second.entry["package_id"])

    def test_ledger_verify_detects_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.jsonl"
            package = Path(tmp) / "package"
            shutil.copytree(EXAMPLE_PACKAGE, package)
            append_ledger_entry(ledger, package, gate="research_gate")
            text = ledger.read_text(encoding="utf-8")
            ledger.write_text(text.replace('"verdict":"blocked"', '"verdict":"revise"'), encoding="utf-8")

            issues = verify_ledger_file(ledger)

        self.assertTrue(any(issue.path == "entry[0].entry_hash" for issue in issues))


if __name__ == "__main__":
    unittest.main()

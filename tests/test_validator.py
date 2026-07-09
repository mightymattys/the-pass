from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import the_pass.validator as validator_module
from the_pass.cli import main as cli_main
from the_pass.ledger import (
    LedgerError,
    append_ledger_entry,
    build_ledger_entry,
    read_ledger_entries,
    verify_ledger_file,
)
from the_pass.validator import default_schema_dir, validate_artifact, validate_package


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


def workflow_artifacts() -> dict[str, dict]:
    artifacts = {
        "hypothesis": {
            "id": "hypothesis-1",
            "created_at": "2026-07-09T00:00:00Z",
            "status": "ready_for_spec",
            "proposed_name": "Synthetic breakout hypothesis",
            "source_notes": ["source_note.yaml"],
            "edge": {
                "primary_family": "trend",
                "thesis": "persistent moves continue after a breakout",
                "mechanism": "slow information diffusion",
            },
            "market": {"asset_classes": ["futures"], "venues": [], "instruments": [], "timeframes": ["1h"]},
            "test": {
                "next_test": "diagnostic screen",
                "required_data": ["adjusted OHLCV"],
                "null_or_random_baseline": "random entries with matched holding period",
                "falsification_criteria": ["net performance does not beat baseline"],
            },
            "risks": {"costs": [], "execution": [], "data": [], "regime": []},
            "kill_when": ["fails the predefined baseline"],
            "blockers": [],
        },
        "screen_report": {
            "id": "screen-1",
            "created_at": "2026-07-09T00:00:00Z",
            "strategy_spec": "strategy_spec.yaml",
            "data_manifest": "",
            "mode": "diagnostic",
            "sample": {"start_time": "", "end_time": "", "instruments": [], "observations": None},
            "variants": {"tried": [], "selected": "", "rejected": []},
            "baseline": {"type": "null_random", "result": ""},
            "costs": {"fee_model": "", "spread_model": "", "slippage_model": "", "assumptions": []},
            "results": {"gross_metrics": {}, "net_metrics": {}, "robustness_notes": []},
            "decision": {"status": "blocked", "reason": "cost model missing", "next_action": "define costs"},
            "safety": {"promotion_claim": False, "live_trading_enabled": False, "real_order_path_available": False},
        },
        "findings": {
            "id": "findings-1",
            "created_at": "2026-07-09T00:00:00Z",
            "package": "package",
            "reviewer": "independent-reviewer",
            "target_gate": "research_gate",
            "findings": [],
            "summary": {"gate_result": "pass", "unresolved_blockers": [], "next_action": "prepare paper plan"},
        },
        "refire_ticket": {
            "id": "refire-1",
            "created_at": "2026-07-09T00:00:00Z",
            "source_finding": "finding-1",
            "package": "package",
            "target_gate": "research_gate",
            "scope": {"allowed_paths": ["runner.py"], "blocked_paths": ["credentials"]},
            "fix_plan": {
                "issue": "timestamp ordering",
                "intended_change": "sort before signal calculation",
                "verification_commands": ["pytest tests/test_runner.py"],
            },
            "result": {"status": "still_blocked", "superseding_package": "", "evidence": []},
        },
        "simmer_laps": {
            "id": "simmer-1",
            "created_at": "2026-07-09T00:00:00Z",
            "target_gate": "research_gate",
            "package": "package",
            "budget": {"max_laps": 2, "stop_condition": "gate passes", "kill_condition": "no progress"},
            "laps": [
                {
                    "lap": 1,
                    "hypothesis": "receipt link is stale",
                    "intended_change": "repair link",
                    "files_touched": ["run_receipt.yaml"],
                    "command": "the-pass validate-package package",
                    "expected_signal": "package validates",
                    "observed_result": "still blocked",
                    "moved_gate": False,
                    "blockers": ["missing costs"],
                }
            ],
            "final": {"status": "blocked", "reason": "missing costs", "next_action": "source fee data"},
        },
        "paper_plan": {
            "id": "paper-1",
            "created_at": "2026-07-09T00:00:00Z",
            "source_package": "",
            "strategy_spec": "",
            "adapter": "",
            "config_hash": "",
            "observation": {"start_after": "", "minimum_days": None, "minimum_signals": None, "instruments": []},
            "decision_logic": {"same_as_backtest": True, "differences": []},
            "divergence_policy": {
                "max_cost_divergence": "",
                "max_signal_divergence": "",
                "max_fill_divergence": "",
                "stop_conditions": [],
            },
            "safety": {
                "simulated_intents_only": True,
                "live_trading_enabled": False,
                "real_order_path_available": False,
                "credentials_required": False,
            },
            "status": "blocked",
        },
        "observation_manifest": {
            "id": "observation-1",
            "created_at": "2026-07-09T00:00:00Z",
            "paper_plan": "paper_plan.yaml",
            "source_package": "package",
            "data_capture": {
                "event_time_field": "event_time",
                "receive_time_field": "receive_time",
                "decision_time_field": "decision_time",
                "storage_path": "observations.jsonl",
            },
            "signals": {"format": "jsonl", "fields": ["event_time", "side"]},
            "simulated_orders": {"format": "jsonl", "fields": ["price", "size"], "cannot_reach_broker": True},
            "quality": {
                "missing_data_policy": "stop",
                "outage_policy": "stop",
                "clock_skew_policy": "block above threshold",
            },
        },
        "divergence_report": {
            "id": "divergence-1",
            "created_at": "2026-07-09T00:00:00Z",
            "paper_plan": "paper_plan.yaml",
            "observation_manifest": "observation_manifest.yaml",
            "sample": {"start_time": "", "end_time": "", "signals": None, "simulated_orders": None},
            "comparisons": {
                "signal_divergence": None,
                "cost_divergence": None,
                "fill_divergence": None,
                "pnl_divergence": None,
            },
            "breaches": [],
            "decision": {"status": "blocked", "reason": "observation incomplete", "next_action": "continue observation"},
        },
        "approval_pack": {
            "id": "approval-1",
            "created_at": "2026-07-09T00:00:00Z",
            "strategy_id": "",
            "requested_gate": "live_gate",
            "config_hash": "",
            "adapter": "",
            "evidence": {"receipts": [], "verdict_reports": [], "paper_reports": [], "risk_reports": []},
            "risk_limits": {"max_notional": "", "max_daily_loss": "", "max_drawdown": "", "kill_switches": []},
            "operations": {"monitoring_plan": "", "rollback_plan": "", "incident_runbook": ""},
            "human_decisions_required": [],
            "safety": {"grants_approval": False, "live_trading_enabled": False, "real_order_path_available": False},
            "status": "blocked",
        },
        "receipt_summary": {
            "id": "summary-1",
            "created_at": "2026-07-09T00:00:00Z",
            "ledger": "",
            "filters": {"strategy_id": "", "gate": "", "verdict": "", "date_range": ""},
            "summary": {"entries": 0, "strategies": [], "verdicts": {}, "open_blockers": []},
            "packages": [],
            "status": "blocked",
        },
    }
    for document in artifacts.values():
        document["schema_version"] = 1
    return artifacts


def prepare_paper_candidate(package: Path, *, reviewer: str = "independent-auditor") -> None:
    adapter_path = package / "adapter.json"
    adapter = json.loads(adapter_path.read_text(encoding="utf-8"))
    adapter["mode"] = "research"
    adapter_path.write_text(json.dumps(adapter), encoding="utf-8")

    metrics_path = package / "metrics_report.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    metrics["gross_metrics"]["pnl"] = 1.0
    metrics["net_metrics"]["pnl"] = 0.5
    metrics["sample"]["trades"] = 10
    metrics["sample"].update(
        {
            "evaluation_scope": "out_of_sample",
            "holdout_start_time": "2026-01-21T00:00:00Z",
            "holdout_end_time": "2026-01-31T00:00:00Z",
        }
    )
    metrics["robustness"]["null_baseline_result"] = "candidate exceeded the matched random baseline"
    metrics["robustness"].update(
        {
            "dsr_or_psr": 0.95,
            "pbo": 0.1,
            "stress_results": ["remains net positive at 1.5x fees and 2x slippage"],
            "parameter_stability": "neighboring parameter values remain net positive",
        }
    )
    metrics_path.write_text(json.dumps(metrics), encoding="utf-8")

    costs_path = package / "cost_waterfall.json"
    costs = json.loads(costs_path.read_text(encoding="utf-8"))
    costs["gross_pnl"] = 1.0
    costs["net_pnl"] = 0.5
    costs["costs"].update({"fees": 0.1, "spread": 0.2, "slippage": 0.2, "funding": 0, "borrow": 0, "roll": 0, "rejects_or_missed_fills": 0})
    costs["assumptions"].update(
        {
            "fee_model": "historical venue fee schedule",
            "fill_model": "touch plus queue haircut",
            "latency_model": "250 ms signal-to-order delay",
            "depth_model": "top-of-book participation capped at 10 percent",
        }
    )
    costs_path.write_text(json.dumps(costs), encoding="utf-8")

    findings = workflow_artifacts()["findings"]
    findings["package"] = "."
    findings["reviewer"] = reviewer
    (package / "findings.json").write_text(json.dumps(findings), encoding="utf-8")

    verdict_path = package / "verdict_report.json"
    verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    verdict["verdict"] = "paper_candidate"
    verdict["owner"] = reviewer
    verdict["gate_results"]["failed_gates"] = []
    verdict_path.write_text(json.dumps(verdict), encoding="utf-8")

    strategy_path = package / "strategy_spec.json"
    strategy = json.loads(strategy_path.read_text(encoding="utf-8"))
    strategy["status"] = "research"
    strategy["execution"].update(
        {
            "order_type": "limit",
            "fill_model": "touch plus queue haircut",
            "fee_model": "historical venue fee schedule",
            "slippage_model": "spread and depth based",
        }
    )
    strategy["validation"]["train_test_split"] = "first 66 percent train, next 14 percent validation"
    strategy["validation"]["holdout_policy"] = "latest 20 percent locked until final review"
    strategy_path.write_text(json.dumps(strategy), encoding="utf-8")


class ValidatorTests(unittest.TestCase):
    def test_rfc3339_date_time_format_is_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "cost_waterfall.json"
            document = json.loads((EXAMPLE_PACKAGE / "cost_waterfall.json").read_text(encoding="utf-8"))

            document["created_at"] = "not-a-date"
            artifact.write_text(json.dumps(document), encoding="utf-8")
            invalid = validate_artifact(artifact, schema_dir=SCHEMA_DIR, artifact_type="cost_waterfall")

            document["created_at"] = "2026-07-09T00:00:00Z"
            artifact.write_text(json.dumps(document), encoding="utf-8")
            valid = validate_artifact(artifact, schema_dir=SCHEMA_DIR, artifact_type="cost_waterfall")

        self.assertFalse(invalid.ok)
        self.assertTrue(
            any(issue.path == "$.created_at" and "date-time" in issue.message for issue in invalid.issues)
        )
        self.assertTrue(valid.ok, [issue.as_dict() for issue in valid.issues])

    def test_foreign_plugin_does_not_supply_default_schemas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            foreign = root / "foreign-plugin"
            packaged = root / "installed" / "the_pass" / "schemas"
            (foreign / ".codex-plugin").mkdir(parents=True)
            (foreign / "schemas").mkdir()
            packaged.mkdir(parents=True)
            (foreign / ".codex-plugin" / "plugin.json").write_text(
                json.dumps({"name": "some-other-plugin"}), encoding="utf-8"
            )
            original_cwd = Path.cwd()
            try:
                os.chdir(foreign)
                with patch.object(validator_module, "__file__", str(packaged.parent / "validator.py")):
                    selected = default_schema_dir()
            finally:
                os.chdir(original_cwd)

        self.assertEqual(selected, packaged.resolve())

    def test_workflow_artifacts_validate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for artifact_type, document in workflow_artifacts().items():
                with self.subTest(artifact_type=artifact_type):
                    artifact = Path(tmp) / f"{artifact_type}.json"
                    artifact.write_text(json.dumps(document), encoding="utf-8")
                    result = validate_artifact(artifact, schema_dir=SCHEMA_DIR, artifact_type=artifact_type)
                    self.assertTrue(result.ok, [issue.as_dict() for issue in result.issues])

    def test_new_schema_minimal_fixtures_validate(self) -> None:
        for artifact_type in ("findings", "screen_report", "paper_plan", "approval_pack"):
            with self.subTest(artifact_type=artifact_type), tempfile.TemporaryDirectory() as tmp:
                artifact = Path(tmp) / f"{artifact_type}.json"
                artifact.write_text(json.dumps(workflow_artifacts()[artifact_type]), encoding="utf-8")

                result = validate_artifact(artifact, schema_dir=SCHEMA_DIR, artifact_type=artifact_type)

                self.assertTrue(result.ok, [issue.as_dict() for issue in result.issues])

    def test_new_schema_missing_required_field_fails(self) -> None:
        for artifact_type in ("findings", "screen_report", "paper_plan", "approval_pack"):
            with self.subTest(artifact_type=artifact_type), tempfile.TemporaryDirectory() as tmp:
                document = workflow_artifacts()[artifact_type]
                del document["created_at"]
                artifact = Path(tmp) / f"{artifact_type}.json"
                artifact.write_text(json.dumps(document), encoding="utf-8")

                result = validate_artifact(artifact, schema_dir=SCHEMA_DIR, artifact_type=artifact_type)

                self.assertFalse(result.ok)
                self.assertTrue(any(issue.path == "$" for issue in result.issues))

    def test_findings_cannot_pass_with_blocking_finding(self) -> None:
        document = workflow_artifacts()["findings"]
        document["findings"] = [
            {
                "id": "finding-1",
                "severity": "P1",
                "status": "confirmed",
                "title": "Lookahead leakage",
                "evidence": {"artifact": "runner.py", "path": "runner.py:10", "note": "future value used"},
                "blocks_promotion": True,
                "recommendation": "fix timestamp alignment",
            }
        ]
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "findings.json"
            artifact.write_text(json.dumps(document), encoding="utf-8")
            result = validate_artifact(artifact, schema_dir=SCHEMA_DIR, artifact_type="findings")

        self.assertFalse(result.ok)
        self.assertTrue(any("unresolved blocking findings" in issue.message for issue in result.issues))

    def test_backtest_candidate_requires_real_screen_sample(self) -> None:
        document = workflow_artifacts()["screen_report"]
        document["decision"]["status"] = "backtest_candidate"
        document["variants"]["tried"] = [{"lookback": 20}]
        document["variants"]["selected"] = "lookback=20"
        document["baseline"]["result"] = "candidate exceeded matched random entries"
        document["costs"].update(
            {"fee_model": "venue fees", "spread_model": "historical spread", "slippage_model": "depth haircut"}
        )
        document["costs"]["assumptions"] = ["pessimistic fill"]
        document["results"] = {"gross_metrics": {"pnl": 1}, "net_metrics": {"pnl": 0.5}, "robustness_notes": ["stable"]}
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "screen_report.json"
            artifact.write_text(json.dumps(document), encoding="utf-8")
            result = validate_artifact(artifact, schema_dir=SCHEMA_DIR, artifact_type="screen_report")

        self.assertFalse(result.ok)
        self.assertTrue(any(issue.path.startswith("$.sample") for issue in result.issues))

    def test_hypothesis_with_blockers_is_not_ready_for_spec(self) -> None:
        document = workflow_artifacts()["hypothesis"]
        document["blockers"] = ["data license unresolved"]
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "hypothesis.json"
            artifact.write_text(json.dumps(document), encoding="utf-8")
            result = validate_artifact(artifact, schema_dir=SCHEMA_DIR, artifact_type="hypothesis")

        self.assertFalse(result.ok)
        self.assertTrue(any(issue.path == "$.blockers" for issue in result.issues))

    def test_research_strategy_spec_requires_falsifiable_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "strategy_spec.json"
            spec = json.loads((EXAMPLE_PACKAGE / "strategy_spec.json").read_text(encoding="utf-8"))
            spec["status"] = "research"
            spec["edge"]["thesis"] = ""
            artifact.write_text(json.dumps(spec), encoding="utf-8")

            result = validate_artifact(artifact, schema_dir=SCHEMA_DIR, artifact_type="strategy_spec")

        self.assertFalse(result.ok)
        self.assertTrue(any(issue.path == "$.edge.thesis" for issue in result.issues))

    def test_approval_pack_cannot_grant_human_approval(self) -> None:
        document = workflow_artifacts()["approval_pack"]
        document["human_decisions_required"] = [
            {"decision": "approve live trading", "owner": "human-risk-owner", "status": "approved"}
        ]
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "approval_pack.json"
            artifact.write_text(json.dumps(document), encoding="utf-8")
            result = validate_artifact(artifact, schema_dir=SCHEMA_DIR, artifact_type="approval_pack")

        self.assertFalse(result.ok)
        self.assertTrue(any(issue.path.endswith("status") for issue in result.issues))

    def test_simmer_stops_after_two_no_progress_laps(self) -> None:
        document = workflow_artifacts()["simmer_laps"]
        first_lap = document["laps"][0]
        document["budget"]["max_laps"] = 3
        document["laps"] = [
            {**first_lap, "lap": 1, "moved_gate": False},
            {**first_lap, "lap": 2, "moved_gate": False},
            {**first_lap, "lap": 3, "moved_gate": True},
        ]
        document["final"] = {"status": "passed", "reason": "late movement", "next_action": "continue"}
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "simmer_laps.json"
            artifact.write_text(json.dumps(document), encoding="utf-8")
            result = validate_artifact(artifact, schema_dir=SCHEMA_DIR, artifact_type="simmer_laps")

        self.assertFalse(result.ok)
        self.assertTrue(any("two consecutive no-progress" in issue.message for issue in result.issues))

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
schema_version: 1
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
schema_version: 1
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

    def test_package_links_must_target_canonical_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "package"
            shutil.copytree(EXAMPLE_PACKAGE, package)
            receipt_path = package / "run_receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["strategy_spec"] = "metrics_report.json"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

            result = validate_package(package, schema_dir=SCHEMA_DIR)

        self.assertFalse(result.ok)
        self.assertTrue(any(issue.path == "$.run_receipt.strategy_spec" for issue in result.issues))

    def test_package_rejects_ambiguous_artifact_extensions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "package"
            shutil.copytree(EXAMPLE_PACKAGE, package)
            shutil.copy(package / "strategy_spec.json", package / "strategy_spec.yaml")

            result = validate_package(package, schema_dir=SCHEMA_DIR)

        self.assertFalse(result.ok)
        self.assertTrue(any("ambiguous artifact strategy_spec" in issue.message for issue in result.issues))

    def test_package_rejects_artifact_symlink_outside_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "package"
            outside_spec = Path(tmp) / "outside-strategy-spec.json"
            shutil.copytree(EXAMPLE_PACKAGE, package)
            shutil.copy(package / "strategy_spec.json", outside_spec)
            (package / "strategy_spec.json").unlink()
            (package / "strategy_spec.json").symlink_to(outside_spec)

            result = validate_package(package, schema_dir=SCHEMA_DIR)

        self.assertFalse(result.ok)
        self.assertTrue(any("escapes package directory" in issue.message for issue in result.issues))

    def test_diagnostic_adapter_cannot_be_paper_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "package"
            shutil.copytree(EXAMPLE_PACKAGE, package)
            verdict_path = package / "verdict_report.json"
            verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
            verdict["verdict"] = "paper_candidate"
            verdict["gate_results"]["failed_gates"] = []
            verdict_path.write_text(json.dumps(verdict, indent=2), encoding="utf-8")

            result = validate_package(package, schema_dir=SCHEMA_DIR)

        self.assertFalse(result.ok)
        self.assertTrue(any("diagnostic adapters cannot produce paper_candidate" in issue.message for issue in result.issues))

    def test_paper_candidate_requires_independent_review_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "package"
            shutil.copytree(EXAMPLE_PACKAGE, package)
            prepare_paper_candidate(package)

            result = validate_package(package, schema_dir=SCHEMA_DIR)

        self.assertTrue(result.ok, [issue.as_dict() for issue in result.issues])

    def test_paper_candidate_rejects_self_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "package"
            shutil.copytree(EXAMPLE_PACKAGE, package)
            prepare_paper_candidate(package, reviewer="the-pass")

            result = validate_package(package, schema_dir=SCHEMA_DIR)

        self.assertFalse(result.ok)
        self.assertTrue(any("must be independent" in issue.message for issue in result.issues))

    def test_paper_candidate_rejects_placeholder_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "package"
            shutil.copytree(EXAMPLE_PACKAGE, package)
            prepare_paper_candidate(package)
            metrics_path = package / "metrics_report.json"
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            metrics["robustness"]["null_baseline_result"] = "not applicable"
            metrics_path.write_text(json.dumps(metrics), encoding="utf-8")

            result = validate_package(package, schema_dir=SCHEMA_DIR)

        self.assertFalse(result.ok)
        self.assertTrue(any("null or random baseline" in issue.message for issue in result.issues))

    def test_paper_candidate_requires_recorded_null_baseline_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "package"
            shutil.copytree(EXAMPLE_PACKAGE, package)
            prepare_paper_candidate(package)
            metrics_path = package / "metrics_report.json"
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            metrics["robustness"]["null_baseline_result"] = ""
            metrics_path.write_text(json.dumps(metrics), encoding="utf-8")

            result = validate_package(package, schema_dir=SCHEMA_DIR)

        self.assertFalse(result.ok)
        self.assertTrue(
            any(
                issue.path == "$.metrics_report.robustness.null_baseline_result"
                and issue.message == "paper_candidate verdicts require a recorded null/random baseline result"
                for issue in result.issues
            )
        )

    def test_paper_candidate_rejects_cost_reconciliation_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "package"
            shutil.copytree(EXAMPLE_PACKAGE, package)
            prepare_paper_candidate(package)
            costs_path = package / "cost_waterfall.json"
            costs = json.loads(costs_path.read_text(encoding="utf-8"))
            costs["net_pnl"] = 0.6
            costs_path.write_text(json.dumps(costs), encoding="utf-8")

            result = validate_package(package, schema_dir=SCHEMA_DIR)

        self.assertFalse(result.ok)
        self.assertTrue(any("gross_pnl minus" in issue.message for issue in result.issues))

    def test_paper_candidate_requires_out_of_sample_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "package"
            shutil.copytree(EXAMPLE_PACKAGE, package)
            prepare_paper_candidate(package)
            metrics_path = package / "metrics_report.json"
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            metrics["sample"]["evaluation_scope"] = "in_sample"
            metrics_path.write_text(json.dumps(metrics), encoding="utf-8")

            result = validate_package(package, schema_dir=SCHEMA_DIR)

        self.assertFalse(result.ok)
        self.assertTrue(any("holdout window" in issue.message for issue in result.issues))

    def test_paper_candidate_requires_reviewed_source_notes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "package"
            shutil.copytree(EXAMPLE_PACKAGE, package)
            prepare_paper_candidate(package)
            source_path = package / "source_note.json"
            source_note = json.loads(source_path.read_text(encoding="utf-8"))
            source_note["status"] = "unread"
            source_path.write_text(json.dumps(source_note), encoding="utf-8")

            result = validate_package(package, schema_dir=SCHEMA_DIR)

        self.assertFalse(result.ok)
        self.assertTrue(any("reviewed or implemented" in issue.message for issue in result.issues))

    def test_data_manifest_requires_sha256_fingerprint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "data_manifest.json"
            manifest = json.loads((EXAMPLE_PACKAGE / "data_manifest.json").read_text(encoding="utf-8"))
            manifest["fingerprint"]["value"] = "not-a-hash"
            artifact.write_text(json.dumps(manifest), encoding="utf-8")

            result = validate_artifact(artifact, schema_dir=SCHEMA_DIR, artifact_type="data_manifest")

        self.assertFalse(result.ok)
        self.assertTrue(any(issue.path == "$.fingerprint.value" for issue in result.issues))

    def test_kill_verdict_requires_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "package"
            shutil.copytree(RANDOM_BASELINE_PACKAGE, package)
            verdict_path = package / "verdict_report.json"
            verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
            verdict["kill_reason"] = ""
            verdict_path.write_text(json.dumps(verdict), encoding="utf-8")

            result = validate_package(package, schema_dir=SCHEMA_DIR)

        self.assertFalse(result.ok)
        self.assertTrue(any("kill_reason" in issue.path for issue in result.issues))

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
        self.assertEqual(entries[0]["package_path"], "package")
        self.assertEqual(entries[0]["cost_waterfall"]["path"], "cost_waterfall.json")
        self.assertEqual(entries[0]["open_blockers"], ["paper promotion blocked by diagnostic adapter mode"])

    def test_missing_ledger_verify_fails_but_summary_succeeds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "missing-ledger.jsonl"
            issues = verify_ledger_file(ledger)

            verify_stderr = io.StringIO()
            with redirect_stderr(verify_stderr):
                verify_exit = cli_main(["receipts", "verify", "--ledger", str(ledger)])

            summary_stdout = io.StringIO()
            with redirect_stdout(summary_stdout):
                summary_exit = cli_main(["receipts", "--ledger", str(ledger)])

        self.assertEqual([issue.message for issue in issues], ["ledger file does not exist"])
        self.assertEqual(verify_exit, 1)
        self.assertIn("ledger file does not exist", verify_stderr.getvalue())
        self.assertEqual(summary_exit, 0)
        self.assertIn("No receipts recorded", summary_stdout.getvalue())

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

    def test_same_package_can_be_recorded_at_distinct_gates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.jsonl"
            package = Path(tmp) / "package"
            shutil.copytree(EXAMPLE_PACKAGE, package)

            first = append_ledger_entry(ledger, package, gate="research_gate")
            second = append_ledger_entry(ledger, package, gate="paper_gate")
            entries = read_ledger_entries(ledger)

        self.assertTrue(first.appended)
        self.assertTrue(second.appended)
        self.assertEqual(len(entries), 2)
        self.assertEqual({entry["gate"] for entry in entries}, {"research_gate", "paper_gate"})

    def test_ledger_paths_remain_valid_when_tree_moves(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            original = Path(tmp) / "original"
            moved = Path(tmp) / "moved"
            original.mkdir()
            package = original / "package"
            ledger = original / "ledger.jsonl"
            shutil.copytree(EXAMPLE_PACKAGE, package)
            append_ledger_entry(ledger, package, gate="research_gate")

            shutil.move(original, moved)
            issues = verify_ledger_file(moved / "ledger.jsonl")

        self.assertFalse(issues, [issue.as_dict() for issue in issues])

    def test_ledger_rejects_invalid_gate_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.jsonl"
            package = Path(tmp) / "package"
            shutil.copytree(EXAMPLE_PACKAGE, package)

            with self.assertRaises(LedgerError):
                append_ledger_entry(ledger, package, gate="Risk Review")

    def test_ledger_verify_detects_artifact_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.jsonl"
            package = Path(tmp) / "package"
            shutil.copytree(EXAMPLE_PACKAGE, package)
            append_ledger_entry(ledger, package, gate="research_gate")
            metrics_path = package / "metrics_report.json"
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            metrics["limitations"].append("changed after receipt")
            metrics_path.write_text(json.dumps(metrics), encoding="utf-8")

            issues = verify_ledger_file(ledger)

        self.assertTrue(any(issue.path.endswith(".sha256") for issue in issues))

    def test_ledger_refuses_append_after_artifact_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.jsonl"
            first_package = Path(tmp) / "first-package"
            second_package = Path(tmp) / "second-package"
            shutil.copytree(EXAMPLE_PACKAGE, first_package)
            shutil.copytree(RANDOM_BASELINE_PACKAGE, second_package)
            append_ledger_entry(ledger, first_package, gate="research_gate")
            metrics_path = first_package / "metrics_report.json"
            metrics_path.write_text(metrics_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

            with self.assertRaises(LedgerError):
                append_ledger_entry(ledger, second_package, gate="research_gate")

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

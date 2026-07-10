from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import yaml

from the_pass.automation import AUTOMATION_COMMANDS, run_automation_spec
from the_pass.engine.baselines import generate_synthetic_bars
from the_pass.incident import build_incident_report
from the_pass.paper import ObservationPolicy, run_virtual_paper_process
from the_pass.reporting import DASHBOARD_VIEWS, build_static_dashboard
from the_pass.risk import build_risk_policy_artifact
from the_pass.validator import validate_artifact


ROOT = Path(__file__).resolve().parents[1]


class PaperRuntimeTests(unittest.TestCase):
    def test_virtual_worker_is_isolated_and_uses_same_decision_code(self) -> None:
        events = generate_synthetic_bars(instrument_id="BTCUSDT", profile="trend")
        with tempfile.TemporaryDirectory() as tmp:
            result = run_virtual_paper_process(
                strategy_name="donchian_momentum",
                events=events,
                risk_policy=build_risk_policy_artifact("crypto_intraday"),
                observation_policy=ObservationPolicy(300_000_000_000, 5_000_000_000, 120_000_000_000),
                observation_time_ns=events[-1].receive_time_ns,
                output_path=Path(tmp) / "paper.json",
            )
        self.assertEqual(result["status"], "complete")
        self.assertTrue(result["process_isolated"])
        self.assertFalse(result["network_clients_loaded"])
        self.assertFalse(result["credentials_present"])
        self.assertEqual(result["signals"], 2)
        self.assertEqual(len(result["fills"]), 2)

    def test_stale_observer_freezes_without_running_strategy(self) -> None:
        events = generate_synthetic_bars(instrument_id="BTCUSDT", profile="trend")
        with tempfile.TemporaryDirectory() as tmp:
            result = run_virtual_paper_process(
                strategy_name="donchian_momentum",
                events=events,
                risk_policy=build_risk_policy_artifact("crypto_intraday"),
                observation_policy=ObservationPolicy(1, 5_000_000_000, 120_000_000_000),
                observation_time_ns=events[-1].receive_time_ns + 2,
                output_path=Path(tmp) / "paper.json",
            )
        self.assertEqual(result["status"], "frozen")
        self.assertEqual(result["breaches"][0]["code"], "stale_data")
        self.assertFalse(result["decision_journal"])


class AutomationTests(unittest.TestCase):
    def test_all_required_job_specs_validate(self) -> None:
        specs = sorted((ROOT / "automations").glob("*.yaml"))
        self.assertEqual(len(specs), 9)
        commands = set()
        for path in specs:
            result = validate_artifact(path, artifact_type="automation_spec")
            self.assertTrue(result.ok, path.name)
            commands.add(yaml.safe_load(path.read_text(encoding="utf-8"))["command"])
        self.assertEqual(commands, set(AUTOMATION_COMMANDS))

    def test_run_is_idempotent_and_enforces_write_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "automations").mkdir()
            spec = yaml.safe_load((ROOT / "automations" / "data-health.yaml").read_text(encoding="utf-8"))
            spec["allowed_writes"] = ["reports/automation"]
            spec_path = root / "automations" / "data-health.yaml"
            spec_path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
            first, first_path = run_automation_spec(
                spec_path,
                output_dir=root / "reports" / "automation",
                scheduled_for="2026-07-10T00:00:00Z",
                workspace_root=root,
            )
            second, second_path = run_automation_spec(
                spec_path,
                output_dir=root / "reports" / "automation",
                scheduled_for="2026-07-10T00:00:00Z",
                workspace_root=root,
            )
            self.assertEqual(first, second)
            self.assertEqual(first_path, second_path)
            with self.assertRaises(ValueError):
                run_automation_spec(
                    spec_path,
                    output_dir=root / "outside",
                    scheduled_for="2026-07-11T00:00:00Z",
                    workspace_root=root,
                )

    def test_gate_checker_cannot_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "automations").mkdir()
            spec = yaml.safe_load((ROOT / "automations" / "gate-checker.yaml").read_text(encoding="utf-8"))
            spec["retry_policy"]["max_attempts"] = 2
            spec["allowed_writes"] = ["reports"]
            spec_path = root / "automations" / "gate-checker.yaml"
            spec_path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
            with self.assertRaises(ValueError):
                run_automation_spec(
                    spec_path,
                    output_dir=root / "reports",
                    scheduled_for="2026-07-10T00:00:00Z",
                    workspace_root=root,
                )


class ReportingAndIncidentTests(unittest.TestCase):
    def test_dashboard_is_static_and_has_every_view(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "dashboard"
            paths = build_static_dashboard(ROOT, output)
            self.assertEqual(len(paths), len(DASHBOARD_VIEWS) + 1)
            for path in paths:
                content = path.read_text(encoding="utf-8").lower()
                self.assertNotIn("<form", content)
                self.assertNotIn("<input", content)
                self.assertNotIn("fetch(", content)

    def test_incident_artifact_is_fail_closed_and_valid(self) -> None:
        document = build_incident_report(
            incident_id="incident-test",
            severity="P2",
            detected_at="2026-07-10T00:00:00Z",
            source="paper_observer",
            summary="stale data",
            evidence=["paper.json"],
            freeze_reason="stale data",
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "incident_report.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            result = validate_artifact(path, artifact_type="incident_report")
        self.assertTrue(result.ok)
        self.assertTrue(document["impact"]["promotion_blocked"])


if __name__ == "__main__":
    unittest.main()

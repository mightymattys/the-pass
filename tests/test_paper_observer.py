from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from the_pass.engine.baselines import generate_synthetic_bars
from the_pass.paper import ObservationPolicy, observe_strategy
from the_pass.risk import build_risk_policy_artifact


STRATEGY = """
from decimal import Decimal
from the_pass.engine.contracts import SimulatedIntent

class Strategy:
    strategy_id = "paper_fixture_v1"
    def on_event(self, event, context):
        if context.event_index:
            return []
        return [SimulatedIntent("entry-1", event.instrument_id, "buy", Decimal("1"), context.decision_time_ns, "bar")]

def build_strategy(config):
    return Strategy()
"""


class PaperObserverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "strategy.py").write_text(STRATEGY, encoding="utf-8")
        self.descriptor = self.root / "descriptor.json"
        self.execution = self.root / "execution.json"
        self.descriptor.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "strategy_id": "paper_fixture_v1",
                    "strategy_file": "strategy.py",
                    "factory": "build_strategy",
                    "config": {},
                    "asset_class": "crypto_spot",
                    "owner": "test",
                }
            ),
            encoding="utf-8",
        )
        self.execution.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "initial_cash": "100000",
                    "fill_model": "bar_next_open",
                    "fee_rate": "0.001",
                    "slippage_bps": "5",
                }
            ),
            encoding="utf-8",
        )
        self.events = generate_synthetic_bars(instrument_id="BTCUSDT", profile="trend")
        self.policy = ObservationPolicy(120_000_000_000, 5_000_000_000, 120_000_000_000)
        self.risk = build_risk_policy_artifact("crypto_intraday")
        self.observation = self.root / "observation"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def observe(self, rows: list, batch_id: str) -> dict:
        return observe_strategy(
            rows,
            batch_id=batch_id,
            descriptor_path=self.descriptor,
            execution_path=self.execution,
            risk_policy=self.risk,
            observation_policy=self.policy,
            observation_time_ns=rows[-1].receive_time_ns,
            observation_dir=self.observation,
            workspace_root=self.root,
        )

    def test_two_batches_resume_and_duplicate_is_idempotent(self) -> None:
        first = self.observe(self.events[:48], "batch-001")
        second = self.observe(self.events[48:], "batch-002")
        duplicate = self.observe(self.events[48:], "batch-002")

        self.assertEqual(first["status"], "observing")
        self.assertEqual(second["events"], len(self.events))
        self.assertEqual(len(second["runs"]), 2)
        self.assertEqual(duplicate["invocation_status"], "duplicate")
        self.assertFalse(second["elapsed_time_verified"])
        self.assertFalse(second["paper_gate_eligible"])
        self.assertEqual(len((self.observation / "invocations.jsonl").read_text().splitlines()), 2)

    def test_conflicting_batch_and_config_drift_freeze_closed(self) -> None:
        self.observe(self.events[:48], "batch-001")
        conflict = self.observe(self.events[1:49], "batch-001")
        self.assertEqual(conflict["status"], "frozen")
        self.assertEqual(conflict["breaches"][0]["code"], "batch_conflict")

        other_root = self.root / "other"
        other_root.mkdir()
        (other_root / "strategy.py").write_text(STRATEGY, encoding="utf-8")
        descriptor = other_root / "descriptor.json"
        execution = other_root / "execution.json"
        descriptor.write_bytes(self.descriptor.read_bytes())
        execution_document = json.loads(self.execution.read_text())
        execution_document["fee_rate"] = "0.002"
        execution.write_text(json.dumps(execution_document), encoding="utf-8")
        observation = other_root / "observation"
        observe_strategy(
            self.events[:48],
            batch_id="batch-001",
            descriptor_path=descriptor,
            execution_path=execution,
            risk_policy=self.risk,
            observation_policy=self.policy,
            observation_time_ns=self.events[47].receive_time_ns,
            observation_dir=observation,
            workspace_root=other_root,
        )
        execution_document["fee_rate"] = "0.003"
        execution.write_text(json.dumps(execution_document), encoding="utf-8")
        drift = observe_strategy(
            self.events[48:],
            batch_id="batch-002",
            descriptor_path=descriptor,
            execution_path=execution,
            risk_policy=self.risk,
            observation_policy=self.policy,
            observation_time_ns=self.events[-1].receive_time_ns,
            observation_dir=observation,
            workspace_root=other_root,
        )
        self.assertEqual(drift["status"], "frozen")
        self.assertEqual(drift["breaches"][0]["code"], "config_drift")

    def test_worker_failure_after_batch_commit_freezes_tracked_state(self) -> None:
        (self.root / "strategy.py").write_text(
            "def build_strategy(config):\n    raise RuntimeError('worker failed')\n",
            encoding="utf-8",
        )

        frozen = self.observe(self.events[:48], "batch-failure")

        self.assertEqual(frozen["status"], "frozen")
        self.assertEqual(frozen["breaches"][0]["code"], "strategy_worker_failure")
        self.assertTrue((self.observation / "batches" / "batch-failure.jsonl").is_file())
        persisted = json.loads(
            (self.observation / "observation.json").read_text(encoding="utf-8")
        )
        self.assertEqual(persisted["batches"][0]["batch_id"], "batch-failure")
        self.assertEqual(
            json.loads(
                (self.observation / "invocations.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()[0]
            )["status"],
            "frozen",
        )
        with self.assertRaisesRegex(RuntimeError, "observation is frozen"):
            self.observe(self.events[:48], "batch-failure")


if __name__ == "__main__":
    unittest.main()

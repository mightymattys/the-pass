from __future__ import annotations

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from the_pass.live_boundary import (
    HumanDecision,
    LockedExecutionGateway,
    build_config_diff,
    build_locked_live_risk_contract,
)
from the_pass.risk import build_risk_policy_artifact
from the_pass.validator import validate_artifact


class LockedBoundaryTests(unittest.TestCase):
    def test_human_decision_cannot_grant_approval(self) -> None:
        decision = HumanDecision("safety_reviewer")
        self.assertEqual(decision.decision, "blocked")
        self.assertFalse(decision.grants_live_approval)
        with self.assertRaises(ValueError):
            HumanDecision("reviewer", decision="approved")
        with self.assertRaises(ValueError):
            HumanDecision("reviewer", grants_live_approval=True)

    def test_gateway_dry_run_has_no_transport_or_side_effect(self) -> None:
        gateway = LockedExecutionGateway()
        proof = gateway.prove_dry_run(
            {"instrument": "TEST", "side": "buy", "quantity": "1"},
            {"strategy": "diagnostic"},
        )
        self.assertFalse(gateway.transport_available)
        self.assertFalse(proof["external_side_effects"])
        self.assertFalse(proof["transport_available"])
        self.assertEqual(proof["result"], "blocked")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "dry_run_proof.json"
            path.write_text(json.dumps(proof), encoding="utf-8")
            self.assertTrue(validate_artifact(path, artifact_type="dry_run_proof").ok)

    def test_config_diff_excludes_secret_keys_and_validates(self) -> None:
        document = build_config_diff({"max_position": 1}, {"max_position": 2})
        with self.assertRaises(ValueError):
            build_config_diff({"api_key": "redacted"}, {"api_key": "changed"})
        with self.assertRaises(ValueError):
            build_config_diff(
                {"venue": {"authentication": {"client_secret": "redacted"}}},
                {"venue": {"authentication": {"client_secret": "changed"}}},
            )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config_diff.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            self.assertTrue(validate_artifact(path, artifact_type="config_diff").ok)

    def test_default_caps_are_hard_maxima_and_contract_is_locked(self) -> None:
        policy = build_risk_policy_artifact("crypto_intraday")
        contract = build_locked_live_risk_contract(Decimal("100000"), policy["policy_hash"])
        self.assertEqual(contract["micro_notional_cap"], 100.0)
        self.assertEqual(contract["daily_loss_cap"], 25.0)
        self.assertEqual(contract["max_leverage"], 1.0)
        self.assertTrue(contract["locked"])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "live_risk_contract.json"
            path.write_text(json.dumps(contract), encoding="utf-8")
            self.assertTrue(validate_artifact(path, artifact_type="live_risk_contract").ok)


if __name__ == "__main__":
    unittest.main()

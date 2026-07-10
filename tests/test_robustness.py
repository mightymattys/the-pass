from __future__ import annotations

import json
import io
import math
import tempfile
import unittest
from decimal import Decimal
from contextlib import redirect_stdout
from pathlib import Path

from the_pass.audit import build_audit_report
from the_pass.cli import main as cli_main
from the_pass.engine.contracts import SimulatedIntent
from the_pass.engine.portfolio import AccountingPortfolio
from the_pass.risk import VersionedRiskPolicy, build_risk_policy_artifact, build_risk_report
from the_pass.robustness import (
    StressParameters,
    block_bootstrap_means,
    cscv_pbo,
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
    purged_walk_forward_splits,
    reality_check,
    regime_statistics,
    run_stress_suite,
    sensitivity_report,
)
from the_pass.validator import validate_artifact


class StatisticalTests(unittest.TestCase):
    def test_purged_walk_forward_has_no_overlap(self) -> None:
        for anchored in (True, False):
            splits = purged_walk_forward_splits(
                100, train_size=30, test_size=10, purge=3, embargo=2, anchored=anchored
            )
            for split in splits:
                self.assertFalse(set(split.train) & set(split.test))
                self.assertFalse(set(split.purged) & set(split.test))
                self.assertEqual(len(split.purged), 3)

    def test_psr_dsr_and_pbo_are_finite_probabilities(self) -> None:
        returns = [0.01, -0.004, 0.008, 0.002, -0.001, 0.006] * 20
        psr = probabilistic_sharpe_ratio(returns)
        dsr = deflated_sharpe_ratio(returns, trial_sharpes=[0.1, 0.2, 0.3, 0.25])
        matrix = [[0.01 + variant * 0.001 if index % 2 else -0.003 * variant for variant in range(4)] for index in range(80)]
        pbo = cscv_pbo(matrix, blocks=8)
        for value in (psr, dsr, pbo["pbo"]):
            self.assertTrue(math.isfinite(value))
            self.assertGreaterEqual(value, 0)
            self.assertLessEqual(value, 1)
        self.assertEqual(pbo["combinations"], 70)

    def test_bootstrap_regime_reality_and_sensitivity_are_deterministic(self) -> None:
        values = [0.01, -0.005, 0.002, 0.004] * 20
        self.assertEqual(
            block_bootstrap_means(values, block_size=4, samples=20, seed=7),
            block_bootstrap_means(values, block_size=4, samples=20, seed=7),
        )
        regimes = regime_statistics(values, ["trend" if index % 2 else "range" for index in range(len(values))])
        self.assertEqual(set(regimes), {"range", "trend"})
        check = reality_check([[value, -value, value / 2] for value in values], bootstrap_samples=100, seed=7)
        self.assertTrue(all(0 <= value <= 1 for value in check.values()))
        sensitivity = sensitivity_report(
            [{"lookback": 5, "sharpe": 0.9}, {"lookback": 10, "sharpe": 1.0}, {"lookback": 20, "sharpe": 0.8}],
            parameter="lookback",
            metric="sharpe",
            selected_value=10,
        )
        self.assertAlmostEqual(sensitivity["max_neighbor_degradation"], 0.2)


class StressAndRiskTests(unittest.TestCase):
    def test_stress_suite_contains_all_mandatory_scenarios(self) -> None:
        results = run_stress_suite(
            StressParameters(
                gross_pnl=Decimal(100),
                fees=Decimal(10),
                slippage=Decimal(5),
                funding=Decimal(2),
                missed_fill_cost=Decimal(3),
                outage_loss=Decimal(20),
                gap_loss=Decimal(40),
                deleverage_loss=Decimal(60),
            )
        )
        names = {result["scenario"] for result in results}
        self.assertTrue(
            {
                "fees_x1_5",
                "slippage_x2",
                "latency_x2",
                "depth_x0_5",
                "depth_x0_25",
                "maker_fill_probability_x0_5",
                "funding_worst_decile",
                "exchange_outage",
                "missing_interval",
                "correlated_gap",
                "forced_deleverage",
            }
            <= names
        )

    def test_policy_hash_is_enforced_and_strategy_cannot_exceed_limit(self) -> None:
        artifact = build_risk_policy_artifact("crypto_intraday")
        policy = VersionedRiskPolicy.from_artifact(artifact)
        portfolio = AccountingPortfolio(Decimal("100000"))
        intent = SimulatedIntent("too-large", "TEST", "buy", Decimal(2), 1, "bar")
        self.assertEqual(policy.allow(intent, portfolio), (False, "max_position_units"))
        tampered = {**artifact, "limits": {**artifact["limits"], "max_position_units": 99}}
        with self.assertRaises(ValueError):
            VersionedRiskPolicy.from_artifact(tampered)
        self.assertLessEqual(policy.kelly_upper_bound(Decimal("0.55"), Decimal("1.5")), Decimal(1))

    def test_risk_artifacts_validate(self) -> None:
        policy = build_risk_policy_artifact("crypto_intraday")
        report = build_risk_report(
            package_id="pkg_test",
            policy=policy,
            returns=[0.01, -0.02, 0.005, -0.001] * 20,
            scenario_losses=[{"scenario": "fees_x1_5", "net_pnl": -1.0, "pass": False}],
            capacity=1000,
            blockers=["synthetic sample"],
        )
        with tempfile.TemporaryDirectory() as tmp:
            policy_path = Path(tmp) / "risk_policy.json"
            report_path = Path(tmp) / "risk_report.json"
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            report_path.write_text(json.dumps(report), encoding="utf-8")
            self.assertTrue(validate_artifact(policy_path, artifact_type="risk_policy").ok)
            self.assertTrue(validate_artifact(report_path, artifact_type="risk_report").ok)

    def test_audit_reviewer_must_be_independent(self) -> None:
        with self.assertRaises(ValueError):
            build_audit_report(
                report_id="audit",
                target="package",
                owner="same",
                reviewer="same",
                findings=[],
                evidence=["receipt"],
                limitations=[],
            )

    def test_robustness_and_risk_cli_outputs(self) -> None:
        matrix = [[0.01 + column * 0.001 if row % 2 else -0.001 for column in range(3)] for row in range(80)]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            matrix_path = root / "matrix.json"
            robust_path = root / "robustness.json"
            returns_path = root / "returns.json"
            scenarios_path = root / "scenarios.json"
            matrix_path.write_text(json.dumps(matrix), encoding="utf-8")
            returns_path.write_text(json.dumps([0.01, -0.005, 0.002, 0.003] * 20), encoding="utf-8")
            scenarios_path.write_text('[{"scenario":"fees_x1_5","net_pnl":1,"pass":true}]', encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                robust_exit = cli_main(
                    [
                        "robustness",
                        "evaluate",
                        "--matrix",
                        str(matrix_path),
                        "--selected-index",
                        "1",
                        "--output",
                        str(robust_path),
                        "--format",
                        "json",
                    ]
                )
                risk_exit = cli_main(
                    [
                        "risk",
                        "build",
                        "--returns",
                        str(returns_path),
                        "--scenarios",
                        str(scenarios_path),
                        "--package-id",
                        "pkg_cli",
                        "--asset-class",
                        "crypto_intraday",
                        "--capacity",
                        "1000",
                        "--blocker",
                        "diagnostic fixture",
                        "--output-dir",
                        str(root / "risk"),
                        "--format",
                        "json",
                    ]
                )
            self.assertEqual(robust_exit, 0)
            self.assertEqual(risk_exit, 2)
            self.assertTrue(robust_path.is_file())
            self.assertTrue((root / "risk" / "risk_report.json").is_file())


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from decimal import Decimal
from pathlib import Path

from the_pass.data.contracts import CanonicalEvent, EventType
from the_pass.cli import main as cli_main
from the_pass.engine.baselines import generate_synthetic_bars
from the_pass.engine.contracts import Fill, SimulatedIntent
from the_pass.engine.costs import LinearCostModel
from the_pass.engine.fills import (
    BarFillModel,
    DiagnosticMidpointFillModel,
    LimitEvidenceFillModel,
    MarketDepthFillModel,
)
from the_pass.engine.portfolio import AccountingPortfolio
from the_pass.engine.screen import ReferenceScreenRunner
from the_pass.validator import validate_package


ROOT = Path(__file__).resolve().parents[1]


def event(
    event_type: EventType,
    *,
    timestamp: int,
    payload: dict[str, object],
    sequence: int = 1,
) -> CanonicalEvent:
    return CanonicalEvent.from_raw(
        raw={"timestamp": timestamp, "payload": payload},
        source="fixture",
        venue="test",
        asset_class="synthetic",
        instrument_id="TEST",
        event_type=event_type,
        event_time_ns=timestamp,
        receive_time_ns=timestamp + 1,
        ingest_id=f"event-{timestamp}",
        sequence=sequence,
        payload=payload,
    )


class FillModelTests(unittest.TestCase):
    def test_market_depth_walk_and_rejects_unavailable_remainder(self) -> None:
        intent = SimulatedIntent("i1", "TEST", "buy", Decimal(3), 1, "market")
        book = event(
            EventType.BOOK_SNAPSHOT,
            timestamp=2,
            payload={"bids": [["99", "2"]], "asks": [["100", "1"], ["101", "1"]]},
        )
        outcome = MarketDepthFillModel().evaluate(intent, book, LinearCostModel(Decimal("0.001")))
        self.assertEqual([fill.price for fill in outcome.fills], [Decimal(100), Decimal(101)])
        self.assertEqual(outcome.remaining_quantity, Decimal(1))
        self.assertEqual(outcome.status, "partial_rejected")
        self.assertEqual(sum((fill.fee for fill in outcome.fills), Decimal(0)), Decimal("0.201"))

    def test_limit_requires_subsequent_evidence_and_applies_haircuts(self) -> None:
        intent = SimulatedIntent("i1", "TEST", "buy", Decimal(10), 10, "limit", Decimal(100))
        same_time = event(EventType.TRADE, timestamp=9, payload={"price": "99", "size": "10"})
        subsequent = event(EventType.TRADE, timestamp=11, payload={"price": "99", "size": "10"})
        model = LimitEvidenceFillModel(Decimal("0.5"), Decimal("0.5"))
        self.assertFalse(model.evaluate(intent, same_time, LinearCostModel()).fills)
        outcome = model.evaluate(intent, subsequent, LinearCostModel())
        self.assertEqual(outcome.fills[0].quantity, Decimal("2.5"))
        self.assertEqual(outcome.remaining_quantity, Decimal("7.5"))

    def test_bar_fill_uses_only_next_bar_and_adverse_slippage(self) -> None:
        intent = SimulatedIntent("i1", "TEST", "buy", Decimal(1), 10, "bar")
        old_bar = event(EventType.BAR, timestamp=9, payload={"open": "100", "close": "100"})
        next_bar = event(EventType.BAR, timestamp=11, payload={"open": "100", "close": "101"})
        model = BarFillModel(Decimal(5))
        self.assertFalse(model.evaluate(intent, old_bar, LinearCostModel()).fills)
        self.assertEqual(model.evaluate(intent, next_bar, LinearCostModel()).fills[0].price, Decimal("100.0500"))

    def test_midpoint_fill_rejects_cross_instrument_book(self) -> None:
        intent = SimulatedIntent("i1", "OTHER", "buy", Decimal(1), 1, "mid_diagnostic")
        book = event(
            EventType.BOOK_SNAPSHOT,
            timestamp=2,
            payload={"bids": [["99", "2"]], "asks": [["101", "2"]]},
        )
        outcome = DiagnosticMidpointFillModel().evaluate(intent, book, LinearCostModel())
        self.assertFalse(outcome.fills)
        self.assertFalse(outcome.promotion_eligible)

    def test_fill_contract_rejects_invalid_amounts(self) -> None:
        with self.assertRaises(ValueError):
            Fill("bad", "TEST", "buy", Decimal("-1"), Decimal(100), 1)
        with self.assertRaises(ValueError):
            Fill("bad", "TEST", "buy", Decimal(1), Decimal(100), 1, fee=Decimal("-1"))


class PortfolioTests(unittest.TestCase):
    def test_known_round_trip_conserves_accounting(self) -> None:
        portfolio = AccountingPortfolio(Decimal("100000"))
        portfolio.apply_fill(Fill("buy", "TEST", "buy", Decimal(1), Decimal(100), 1, Decimal(1)))
        snapshot = portfolio.mark("TEST", Decimal(110), 2)
        self.assertEqual(snapshot["equity"], Decimal("100009"))
        portfolio.apply_fill(Fill("sell", "TEST", "sell", Decimal(1), Decimal(110), 3, Decimal(1)))
        self.assertEqual(portfolio.realized_pnl, Decimal(10))
        self.assertEqual(portfolio.fees, Decimal(2))
        self.assertEqual(portfolio.equity(), Decimal("100008"))
        portfolio.assert_conservation()


class ScreenTests(unittest.TestCase):
    def test_every_preregistered_variant_has_a_result(self) -> None:
        try:
            import pandas  # noqa: F401
        except ImportError:
            self.skipTest("pandas is provided by the research extra")
        bars = generate_synthetic_bars(instrument_id="TEST", profile="trend")
        variants = [{"lookback": 5}, {"lookback": 10}, {"lookback": 20}]
        results = ReferenceScreenRunner().run(
            [Decimal(str(item.payload["close"])) for item in bars], family="donchian", variants=variants
        )
        self.assertEqual([result["parameters"] for result in results], variants)
        self.assertTrue(all(result["observations"] == len(bars) for result in results))


class BaselineGoldenTests(unittest.TestCase):
    def test_exact_golden_net_results(self) -> None:
        expected = {
            "buy_hold": "24.515137425",
            "seeded_random": "-5.41784016",
            "donchian_momentum": "21.009885675",
            "mean_reversion": "-2.145125925",
        }
        for name, expected_pnl in expected.items():
            metrics = json.loads(
                (ROOT / "examples" / "b2-baselines" / name / "package" / "metrics_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(Decimal(str(metrics["net_metrics"]["pnl"])), Decimal(expected_pnl), name)

    @unittest.skipUnless(importlib.util.find_spec("pandas"), "pandas is provided by the research extra")
    def test_backtest_cli_builds_a_valid_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "package"
            with redirect_stdout(io.StringIO()) as output:
                exit_code = cli_main(
                    ["backtest", "baseline", "--name", "buy_hold", "--output", str(package), "--format", "json"]
                )
            envelope = json.loads(output.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertTrue(envelope["ok"])
            self.assertTrue(validate_package(package).ok)
            metrics = json.loads((package / "metrics_report.json").read_text(encoding="utf-8"))
            self.assertEqual(metrics["annualization"]["calendar"], "continuous_365.25_days")
            self.assertNotEqual(metrics["gross_metrics"]["sharpe"], metrics["net_metrics"]["sharpe"])

    @unittest.skipUnless(importlib.util.find_spec("pandas"), "pandas is provided by the research extra")
    def test_screen_cli_emits_every_variant(self) -> None:
        bars = generate_synthetic_bars(instrument_id="TEST", profile="trend")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            closes = root / "closes.json"
            variants = root / "variants.json"
            output = root / "screen.json"
            closes.write_text(json.dumps([str(bar.payload["close"]) for bar in bars]), encoding="utf-8")
            variants.write_text('[{"lookback": 5}, {"lookback": 10}]', encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                exit_code = cli_main(
                    [
                        "screen",
                        "run",
                        "--closes",
                        str(closes),
                        "--variants",
                        str(variants),
                        "--family",
                        "donchian",
                        "--output",
                        str(output),
                        "--format",
                        "json",
                    ]
                )
            self.assertEqual(exit_code, 0)
            self.assertEqual(len(json.loads(output.read_text(encoding="utf-8"))), 2)


if __name__ == "__main__":
    unittest.main()

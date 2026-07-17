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
from the_pass.engine.contracts import Fill, RunnerResult, SimulatedIntent
from the_pass.engine.costs import LinearCostModel
from the_pass.engine.fills import (
    BarFillModel,
    DiagnosticMidpointFillModel,
    LimitEvidenceFillModel,
    MarketDepthFillModel,
)
from the_pass.engine.package import preregister_search_space, write_run_package
from the_pass.engine.portfolio import AccountingPortfolio
from the_pass.engine.reporting import build_metrics_and_costs
from the_pass.engine.screen import ReferenceScreenRunner
from the_pass.engine.simulator import EventSimulator
from the_pass.engine.workflows import run_baseline
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
        old_bar = event(EventType.BAR, timestamp=9, payload={"open": "100", "close": "100", "volume": "10"})
        next_bar = event(EventType.BAR, timestamp=11, payload={"open": "100", "close": "101", "volume": "10"})
        model = BarFillModel(Decimal(5))
        self.assertFalse(model.evaluate(intent, old_bar, LinearCostModel()).fills)
        self.assertEqual(model.evaluate(intent, next_bar, LinearCostModel()).fills[0].price, Decimal("100.0500"))

    def test_bar_fill_caps_oversized_intent_at_ten_percent_of_volume(self) -> None:
        intent = SimulatedIntent("large", "TEST", "buy", Decimal(20), 10, "bar")
        next_bar = event(
            EventType.BAR,
            timestamp=11,
            payload={"open": "100", "close": "101", "volume": "50"},
        )
        outcome = BarFillModel().evaluate(intent, next_bar, LinearCostModel())
        self.assertEqual(outcome.fills[0].quantity, Decimal("5.0"))
        self.assertEqual(outcome.remaining_quantity, Decimal("15.0"))
        self.assertEqual(outcome.status, "partial")

    def test_bar_fill_does_not_fill_zero_or_missing_volume(self) -> None:
        intent = SimulatedIntent("no-volume", "TEST", "buy", Decimal(1), 10, "bar")
        for payload in (
            {"open": "100", "close": "101", "volume": "0"},
            {"open": "100", "close": "101"},
        ):
            with self.subTest(payload=payload):
                outcome = BarFillModel().evaluate(
                    intent,
                    event(EventType.BAR, timestamp=11, payload=payload),
                    LinearCostModel(),
                )
                self.assertFalse(outcome.fills)
                self.assertEqual(outcome.remaining_quantity, Decimal(1))

    def test_favorable_passive_price_has_zero_spread_cost(self) -> None:
        intent = SimulatedIntent("passive", "TEST", "buy", Decimal(2), 1, "limit", Decimal(99))
        costs = LinearCostModel().costs(
            intent,
            Decimal(99),
            Decimal(2),
            reference_mid=Decimal(100),
        )
        self.assertEqual(costs["spread"], Decimal(0))

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

    def test_execution_v2_enforces_latency_participation_dynamic_fee_and_impact(
        self,
    ) -> None:
        intent = SimulatedIntent(
            "i-v2", "TEST", "buy", Decimal(10), 10, "market"
        )
        too_early = event(
            EventType.BOOK_SNAPSHOT,
            timestamp=11,
            payload={
                "bids": [["99", "8"]],
                "asks": [["100", "8"]],
                "fee_rate": "0.002",
            },
        )
        eligible = event(
            EventType.BOOK_SNAPSHOT,
            timestamp=12,
            payload={
                "bids": [["99", "8"]],
                "asks": [["100", "8"]],
                "fee_rate": "0.002",
            },
        )
        model = MarketDepthFillModel(
            minimum_latency_ns=2,
            participation_rate=Decimal("0.25"),
        )
        costs = LinearCostModel(
            fee_rate=Decimal("0.001"), impact_bps=Decimal("10")
        )
        self.assertFalse(model.evaluate(intent, too_early, costs).fills)
        fill = model.evaluate(intent, eligible, costs).fills[0]
        self.assertEqual(fill.quantity, Decimal(2))
        self.assertEqual(fill.fee, Decimal("0.4"))
        self.assertEqual(fill.impact_cost, Decimal("0.2"))
        self.assertEqual(fill.latency_ns, 3)


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

    def test_futures_multiplier_funding_and_settlement_conserve_equity(self) -> None:
        portfolio = AccountingPortfolio(Decimal("100000"))
        portfolio.register_instrument(
            "ES",
            instrument_type="future",
            multiplier=Decimal(50),
        )
        portfolio.apply_fill(
            Fill("buy-es", "ES", "buy", Decimal(2), Decimal(100), 1)
        )
        self.assertEqual(
            portfolio.mark("ES", Decimal(110), 2)["equity"],
            Decimal("101000"),
        )
        funding = portfolio.apply_funding_rate(
            "ES", rate=Decimal("0.01"), price=Decimal(110)
        )
        self.assertEqual(funding, Decimal(110))
        self.assertEqual(portfolio.equity(), Decimal("100890"))
        realized = portfolio.settle_position("ES", Decimal(105))
        self.assertEqual(realized, Decimal(500))
        self.assertEqual(portfolio.equity(), Decimal("100390"))
        portfolio.assert_conservation()

    def test_short_funding_is_a_credit_and_prediction_settlement_closes_inventory(
        self,
    ) -> None:
        future = AccountingPortfolio(Decimal("100000"))
        future.register_instrument(
            "PERP",
            instrument_type="future",
            multiplier=Decimal(1),
        )
        future.apply_fill(
            Fill("short", "PERP", "sell", Decimal(2), Decimal(100), 1)
        )
        credit = future.apply_funding_rate(
            "PERP", rate=Decimal("0.01"), price=Decimal(100)
        )
        self.assertEqual(credit, Decimal("-2"))
        self.assertEqual(future.equity(), Decimal("100002"))

        prediction = AccountingPortfolio(Decimal("100"))
        prediction.register_instrument(
            "YES",
            instrument_type="prediction",
            multiplier=Decimal(1),
        )
        prediction.apply_fill(
            Fill("buy-yes", "YES", "buy", Decimal(1), Decimal("0.4"), 1)
        )
        prediction.settle_position("YES", Decimal(1))
        self.assertEqual(prediction.positions["YES"], Decimal(0))
        self.assertEqual(prediction.equity(), Decimal("100.6"))
        prediction.assert_conservation()


class SimulatorRealismTests(unittest.TestCase):
    class NoOpStrategy:
        strategy_id = "no-op"

        def on_event(self, replay_event, context):
            return ()

    class EmitOnceStrategy:
        strategy_id = "emit-once"

        def __init__(self, quantities: tuple[Decimal, ...]) -> None:
            self.quantities = quantities

        def on_event(self, replay_event, context):
            if context.event_index != 0:
                return ()
            return tuple(
                SimulatedIntent(
                    intent_id=f"intent-{index}",
                    instrument_id=replay_event.instrument_id,
                    side="buy",
                    quantity=quantity,
                    decision_time_ns=context.decision_time_ns,
                    intent_type="bar",
                )
                for index, quantity in enumerate(self.quantities)
            )

    @staticmethod
    def bars(*, final_volume: str) -> list[CanonicalEvent]:
        return [
            event(
                EventType.BAR,
                timestamp=timestamp,
                sequence=timestamp,
                payload={
                    "open": "100",
                    "close": "100",
                    "volume": volume,
                },
            )
            for timestamp, volume in ((1, "100"), (2, final_volume))
        ]

    def test_bar_participation_budget_is_shared_across_pending_intents(self) -> None:
        result = EventSimulator(
            fill_model=BarFillModel(),
            cost_model=LinearCostModel(),
        ).run(
            self.EmitOnceStrategy((Decimal(10), Decimal(10))),
            self.bars(final_volume="100"),
        )
        self.assertEqual(
            sum((fill.quantity for fill in result.fills), Decimal(0)),
            Decimal(10),
        )
        self.assertEqual(result.missed[0]["reason"], "bar participation cap")

    def test_terminal_capped_remainder_keeps_participation_reason(self) -> None:
        result = EventSimulator(
            fill_model=BarFillModel(),
            cost_model=LinearCostModel(),
        ).run(
            self.EmitOnceStrategy((Decimal(20),)),
            self.bars(final_volume="50"),
        )
        self.assertEqual(result.fills[0].quantity, Decimal(5))
        self.assertEqual(result.missed[0]["quantity"], Decimal(15))
        self.assertEqual(result.missed[0]["reason"], "bar participation cap")

    def test_late_arrival_receive_time_inversion_is_rejected(self) -> None:
        early_event_late_receive = CanonicalEvent.from_raw(
            raw={"row": 1},
            source="fixture",
            venue="test",
            asset_class="crypto_spot",
            instrument_id="TEST",
            event_type=EventType.BAR,
            event_time_ns=1,
            receive_time_ns=100,
            ingest_id="late-first",
            payload={"open": "100", "close": "100", "volume": "1"},
        )
        later_event_early_receive = CanonicalEvent.from_raw(
            raw={"row": 2},
            source="fixture",
            venue="test",
            asset_class="crypto_spot",
            instrument_id="TEST",
            event_type=EventType.BAR,
            event_time_ns=2,
            receive_time_ns=10,
            ingest_id="early-second",
            payload={"open": "100", "close": "100", "volume": "1"},
        )
        simulator = EventSimulator(
            fill_model=BarFillModel(), cost_model=LinearCostModel()
        )
        with self.assertRaisesRegex(ValueError, "receive_time_inversion"):
            simulator.run(
                self.NoOpStrategy(),
                [early_event_late_receive, later_event_early_receive],
            )

    def test_checkpointed_and_single_pass_equity_sampling_match(self) -> None:
        events = [
            CanonicalEvent.from_raw(
                raw={"row": index},
                source="fixture",
                venue="test",
                asset_class="crypto_spot",
                instrument_id="TEST",
                event_type=EventType.BAR,
                event_time_ns=index,
                receive_time_ns=index + 1,
                ingest_id=f"sample-{index}",
                sequence=index,
                payload={"open": "100", "close": "100", "volume": "1"},
            )
            for index in range(100)
        ]
        simulator = EventSimulator(
            fill_model=BarFillModel(),
            cost_model=LinearCostModel(),
            equity_sampling_interval=10,
        )
        single = simulator.run(self.NoOpStrategy(), events)
        first = simulator.run_ordered(
            self.NoOpStrategy(),
            events[:50],
            total_events=50,
            instrument_ids={"TEST"},
            checkpoint_mode=True,
        )
        chunked = simulator.run_ordered(
            self.NoOpStrategy(),
            events[50:],
            total_events=50,
            instrument_ids={"TEST"},
            checkpoint=first.checkpoint,
        )
        self.assertEqual(chunked.equity_curve, single.equity_curve)


class ReportingRealismTests(unittest.TestCase):
    @staticmethod
    def result(
        *,
        equities: list[Decimal],
        fills: list[Fill] | None = None,
        diagnostics: dict[str, object] | None = None,
    ) -> RunnerResult:
        curve = [
            {"event_time_ns": (index + 1) * 1_000_000_000, "equity": value}
            for index, value in enumerate(equities)
        ]
        return RunnerResult(
            strategy_id="reporting-test",
            events_processed=len(curve),
            signals=0,
            intents=[],
            fills=fills or [],
            rejected=[],
            missed=[],
            equity_curve=curve,
            cost_components={
                name: Decimal(0)
                for name in (
                    "fees",
                    "spread",
                    "slippage",
                    "impact",
                    "funding",
                    "borrow",
                    "roll",
                    "rejects_or_missed_fills",
                )
            },
            final_snapshot={"equity": equities[-1]},
            diagnostics=diagnostics or {},
        )

    def test_zero_equity_hard_flags_metrics_and_promotion(self) -> None:
        metrics, _costs = build_metrics_and_costs(
            self.result(equities=[Decimal(100), Decimal(0)]),
            initial_cash=Decimal(100),
            created_at="2026-07-17T00:00:00Z",
            start_time="2026-07-17T00:00:00Z",
            end_time="2026-07-17T00:00:01Z",
            asset_class="crypto_spot",
        )
        self.assertFalse(metrics["promotion_eligible"])
        self.assertIn("equity reached zero — metrics invalid", metrics["limitations"])
        self.assertTrue(all(value is None for value in metrics["net_metrics"].values()))

    def test_turnover_uses_futures_multiplier(self) -> None:
        fill = Fill(
            "future-fill",
            "ES",
            "buy",
            Decimal(2),
            Decimal(100),
            1_000_000_000,
        )
        metrics, _costs = build_metrics_and_costs(
            self.result(
                equities=[Decimal(100_000), Decimal(100_000)],
                fills=[fill],
                diagnostics={"instrument_multipliers": {"ES": "50"}},
            ),
            initial_cash=Decimal(100_000),
            created_at="2026-07-17T00:00:00Z",
            start_time="2026-07-17T00:00:00Z",
            end_time="2026-07-17T00:00:01Z",
            asset_class="futures",
        )
        self.assertEqual(metrics["net_metrics"]["turnover"], 0.1)

    def test_nonempty_multiplier_map_must_cover_every_fill(self) -> None:
        fill = Fill(
            "future-fill",
            "ES",
            "buy",
            Decimal(1),
            Decimal(100),
            1_000_000_000,
        )
        with self.assertRaisesRegex(
            ValueError, "instrument_multipliers is missing fill instruments: ES"
        ):
            build_metrics_and_costs(
                self.result(
                    equities=[Decimal(100_000), Decimal(100_000)],
                    fills=[fill],
                    diagnostics={"instrument_multipliers": {"NQ": "20"}},
                ),
                initial_cash=Decimal(100_000),
                created_at="2026-07-17T00:00:00Z",
                start_time="2026-07-17T00:00:00Z",
                end_time="2026-07-17T00:00:01Z",
                asset_class="futures",
            )

    def test_zero_equity_run_writes_complete_blocked_package(self) -> None:
        result = self.result(equities=[Decimal(100), Decimal(0)])
        search_space = {
            "schema_version": 1,
            "registered_at": "2026-07-17T00:00:00Z",
            "family": "zero-equity-proof",
            "variants": [{}],
            "selection_policy": "fixed test fixture",
            "selected_variant_id": 0,
        }
        events = [
            event(
                EventType.BAR,
                timestamp=timestamp * 1_000_000_000,
                sequence=timestamp,
                payload={
                    "open": "100",
                    "high": "100",
                    "low": "100",
                    "close": "100",
                    "volume": "100",
                },
            )
            for timestamp in (1, 2)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "package"
            preregister_search_space(package, search_space)
            write_run_package(
                package,
                result=result,
                events=events,
                search_space=search_space,
                initial_cash=Decimal(100),
                asset_class="crypto_spot",
                random_seed=None,
            )
            validation = validate_package(package)
            metrics = json.loads(
                (package / "metrics_report.json").read_text(encoding="utf-8")
            )
            verdict = json.loads(
                (package / "verdict_report.json").read_text(encoding="utf-8")
            )
            markdown = (package / "run_report.md").read_text(encoding="utf-8")
            self.assertTrue(validation.ok, validation.issues)
            self.assertFalse(metrics["promotion_eligible"])
            self.assertEqual(verdict["verdict"], "blocked")
            self.assertIn("N/A", markdown)
            self.assertIn("equity reached zero — metrics invalid", markdown)
            self.assertTrue((package / "receipt-ledger.jsonl").is_file())


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
    def test_fresh_buy_hold_run_matches_inline_golden_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = run_baseline("buy_hold", Path(tmp) / "package")
            metrics = json.loads(
                (package / "metrics_report.json").read_text(encoding="utf-8")
            )

        self.assertEqual(Decimal(str(metrics["gross_metrics"]["pnl"])), Decimal("24.85"))
        self.assertEqual(
            Decimal(str(metrics["net_metrics"]["pnl"])),
            Decimal("24.515137425"),
        )
        self.assertEqual(
            Decimal(str(metrics["gross_metrics"]["sharpe"])),
            Decimal("629.158765661"),
        )
        self.assertEqual(
            Decimal(str(metrics["net_metrics"]["sharpe"])),
            Decimal("616.183460291"),
        )

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

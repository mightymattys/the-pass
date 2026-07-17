"""Public B2 baseline workflow entry points used by CLI and scripts."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

from the_pass.data.contracts import CanonicalEvent, EventType

from .baselines import (
    BuyAndHoldBaseline,
    DonchianMomentumBaseline,
    FUTURES_TREND_CONTRACT_MULTIPLIER,
    FuturesTrendBaseline,
    SeededRandomBaseline,
    VolatilityFilteredMeanReversionBaseline,
    generate_synthetic_bars,
    scan_prediction_complements,
    with_synthetic_instrument_definition,
)
from .contracts import RunnerResult
from .costs import LinearCostModel
from .fills import BarFillModel
from .package import preregister_search_space, write_run_package
from .screen import ReferenceScreenRunner
from .simulator import EventSimulator


INITIAL_CASH = Decimal("100000")
BASELINE_NAMES = (
    "buy_hold",
    "seeded_random",
    "donchian_momentum",
    "mean_reversion",
    "futures_trend",
    "prediction_complement",
)


def make_baseline_strategy(name: str) -> Any:
    if name == "buy_hold":
        return BuyAndHoldBaseline()
    if name == "seeded_random":
        return SeededRandomBaseline(7)
    if name == "donchian_momentum":
        return DonchianMomentumBaseline(10)
    if name == "mean_reversion":
        return VolatilityFilteredMeanReversionBaseline(12, 1.0, 0.03)
    if name == "futures_trend":
        return FuturesTrendBaseline(10)
    raise ValueError(f"baseline has no event strategy: {name}")


def _search_space(family: str, variants: list[dict[str, Any]], selected: int = 0) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "registered_at": "2026-07-10T00:00:00Z",
        "family": family,
        "variants": variants,
        "selection_policy": "fixed diagnostic baseline chosen before event simulation",
        "selected_variant_id": selected,
    }


def _event_definition(name: str) -> tuple[Any, list[CanonicalEvent], str, list[dict[str, Any]], int, str, int | None, str]:
    if name == "buy_hold":
        return make_baseline_strategy(name), generate_synthetic_bars(instrument_id="BTCUSDT", profile="trend"), "buy_hold", [{}], 0, "crypto_spot", None, "blocked"
    if name == "seeded_random":
        return make_baseline_strategy(name), generate_synthetic_bars(instrument_id="BTCUSDT", profile="flat"), "random", [{"seed": 7}], 0, "crypto_spot", 7, "kill"
    if name == "donchian_momentum":
        return make_baseline_strategy(name), generate_synthetic_bars(instrument_id="BTCUSDT", profile="trend"), "donchian", [{"lookback": 5}, {"lookback": 10}, {"lookback": 20}], 1, "crypto_spot", None, "blocked"
    if name == "mean_reversion":
        return make_baseline_strategy(name), generate_synthetic_bars(instrument_id="ETHUSDT", profile="mean_reversion"), "mean_reversion", [{"lookback": 8, "entry_z": "0.8"}, {"lookback": 12, "entry_z": "1.0"}, {"lookback": 20, "entry_z": "1.2"}], 1, "crypto_spot", None, "blocked"
    if name == "futures_trend":
        bars = generate_synthetic_bars(
            instrument_id="ES_CONT",
            profile="trend",
            asset_class="futures",
        )
        events = with_synthetic_instrument_definition(
            bars,
            multiplier=FUTURES_TREND_CONTRACT_MULTIPLIER,
        )
        return make_baseline_strategy(name), events, "donchian", [{"lookback": 10}, {"lookback": 20}], 0, "futures", None, "blocked"
    raise ValueError(f"unknown event baseline: {name}")


def _synthetic_books(count: int = 48) -> tuple[list[CanonicalEvent], list[dict[str, Decimal]]]:
    events = []
    snapshots = []
    start = 1_704_067_200_000_000_000
    for index in range(count):
        yes_ask = Decimal("0.48") + Decimal(index % 5) / Decimal(100)
        no_ask = Decimal("0.49") + Decimal((index + 2) % 4) / Decimal(100)
        snapshots.append({"yes_ask": yes_ask, "no_ask": no_ask})
        timestamp = start + index * 60_000_000_000
        events.append(
            CanonicalEvent.from_raw(
                raw={"index": index, "yes_ask": format(yes_ask, "f"), "no_ask": format(no_ask, "f")},
                source="the-pass-synthetic",
                venue="synthetic",
                asset_class="prediction_market",
                instrument_id="SYNTHETIC_YES",
                event_type=EventType.BOOK_SNAPSHOT,
                event_time_ns=timestamp,
                receive_time_ns=timestamp + 1_000_000,
                ingest_id=f"prediction-book-{index:04d}",
                sequence=index,
                payload={
                    "hash": f"synthetic-{index:04d}",
                    "bids": [[yes_ask - Decimal("0.02"), Decimal(100)]],
                    "asks": [[yes_ask, Decimal(100)]],
                    "complementary_ask": no_ask,
                },
            )
        )
    return events, snapshots


def run_baseline(name: str, output_package: Path) -> Path:
    if name not in BASELINE_NAMES:
        raise ValueError(f"unknown baseline {name}; choose from: {', '.join(BASELINE_NAMES)}")
    if name != "prediction_complement":
        strategy, events, family, variants, selected, asset_class, seed, verdict = _event_definition(name)
        registered = _search_space(family, variants, selected)
        preregister_search_space(output_package, registered)
        screen_results = ReferenceScreenRunner().run(
            [
                Decimal(str(event.payload["close"]))
                for event in events
                if event.event_type == EventType.BAR
            ],
            family=family,
            variants=variants,
        )
        result = EventSimulator(
            fill_model=BarFillModel(Decimal(5)),
            cost_model=LinearCostModel(Decimal("0.001")),
            initial_cash=INITIAL_CASH,
        ).run(strategy, events)
        return write_run_package(
            output_package,
            result=result,
            events=events,
            search_space=registered,
            initial_cash=INITIAL_CASH,
            asset_class=asset_class,
            random_seed=seed,
            verdict=verdict,
            screen_results=screen_results,
        )

    variants = [{"gross_edge_threshold": "0.00"}]
    registered = _search_space("prediction_complement", variants)
    preregister_search_space(output_package, registered)
    events, snapshots = _synthetic_books()
    diagnostic = scan_prediction_complements(snapshots)
    final_snapshot = {
        "event_time_ns": events[-1].receive_time_ns,
        "cash": INITIAL_CASH,
        "collateral": Decimal(0),
        "equity": INITIAL_CASH,
        "realized_pnl": Decimal(0),
        "unrealized_pnl": Decimal(0),
        "fees": Decimal(0),
        "funding": Decimal(0),
        "borrow": Decimal(0),
        "roll": Decimal(0),
        "opportunity_cost": Decimal(0),
        "positions": {},
    }
    result = RunnerResult(
        strategy_id="prediction_market_complement_or_fair_value_v1",
        events_processed=len(events),
        signals=len(diagnostic["opportunities"]),
        intents=[],
        fills=[],
        rejected=[],
        missed=[],
        equity_curve=[{"event_time_ns": event.receive_time_ns, "equity": INITIAL_CASH} for event in events],
        cost_components={name: Decimal(0) for name in ("fees", "spread", "slippage", "funding", "borrow", "roll", "rejects_or_missed_fills")},
        final_snapshot=final_snapshot,
        diagnostics=diagnostic,
    )
    return write_run_package(
        output_package,
        result=result,
        events=events,
        search_space=registered,
        initial_cash=INITIAL_CASH,
        asset_class="prediction_market",
        random_seed=None,
        screen_results=[{"variant_id": 0, "parameters": variants[0], **diagnostic}],
    )

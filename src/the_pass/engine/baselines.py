"""Deterministic baseline strategies and public synthetic event generators."""

from __future__ import annotations

import random
from decimal import Decimal
from statistics import mean, pstdev
from typing import Sequence

from the_pass.data.contracts import CanonicalEvent, EventType

from .contracts import RunnerContext, SimulatedIntent


class TargetPositionStrategy:
    strategy_id = "target-position-base"

    def __init__(self) -> None:
        self._intent_number = 0

    def target(self, event: CanonicalEvent, context: RunnerContext) -> Decimal | None:
        raise NotImplementedError

    def on_event(self, event: CanonicalEvent, context: RunnerContext) -> Sequence[SimulatedIntent]:
        if event.event_type != EventType.BAR or context.event_index == context.total_events - 1:
            return ()
        target = self.target(event, context)
        if target is None:
            return ()
        current = context.positions.get(event.instrument_id, Decimal(0))
        delta = target - current
        if delta == 0:
            return ()
        self._intent_number += 1
        return (
            SimulatedIntent(
                intent_id=f"{self.strategy_id}-{self._intent_number}",
                instrument_id=event.instrument_id,
                side="buy" if delta > 0 else "sell",
                quantity=abs(delta),
                decision_time_ns=context.decision_time_ns,
                intent_type="bar",
            ),
        )


class BuyAndHoldBaseline(TargetPositionStrategy):
    strategy_id = "crypto_spot_buy_hold_benchmark_v1"

    def target(self, event: CanonicalEvent, context: RunnerContext) -> Decimal | None:
        if context.event_index == 0:
            return Decimal(1)
        if context.event_index == context.total_events - 2:
            return Decimal(0)
        return None


class SeededRandomBaseline(TargetPositionStrategy):
    strategy_id = "null_random_control_v1"

    def __init__(self, seed: int = 7) -> None:
        super().__init__()
        self.random = random.Random(seed)

    def target(self, event: CanonicalEvent, context: RunnerContext) -> Decimal | None:
        if context.event_index == context.total_events - 2:
            return Decimal(0)
        if context.event_index % 3:
            return None
        return Decimal(self.random.choice((-1, 0, 1)))


class DonchianMomentumBaseline(TargetPositionStrategy):
    strategy_id = "crypto_spot_time_series_momentum_v1"

    def __init__(self, lookback: int = 10) -> None:
        super().__init__()
        if lookback < 2:
            raise ValueError("lookback must be at least two")
        self.lookback = lookback
        self.closes: list[Decimal] = []

    def target(self, event: CanonicalEvent, context: RunnerContext) -> Decimal | None:
        close = Decimal(str(event.payload["close"]))
        if context.event_index == context.total_events - 2:
            self.closes.append(close)
            return Decimal(0)
        target = None
        if len(self.closes) >= self.lookback:
            window = self.closes[-self.lookback :]
            if close > max(window):
                target = Decimal(1)
            elif close < min(window):
                target = Decimal(-1)
        self.closes.append(close)
        return target


class VolatilityFilteredMeanReversionBaseline(TargetPositionStrategy):
    strategy_id = "volatility_filtered_mean_reversion_v1"

    def __init__(self, lookback: int = 12, entry_z: float = 1.0, max_volatility: float = 0.03) -> None:
        super().__init__()
        self.lookback = lookback
        self.entry_z = entry_z
        self.max_volatility = max_volatility
        self.closes: list[float] = []

    def target(self, event: CanonicalEvent, context: RunnerContext) -> Decimal | None:
        close = float(event.payload["close"])
        if context.event_index == context.total_events - 2:
            self.closes.append(close)
            return Decimal(0)
        target = None
        if len(self.closes) >= self.lookback:
            window = self.closes[-self.lookback :]
            center = mean(window)
            deviation = pstdev(window)
            returns = [window[index] / window[index - 1] - 1 for index in range(1, len(window))]
            volatility = pstdev(returns) if len(returns) > 1 else 0.0
            if deviation > 0 and volatility <= self.max_volatility:
                z_score = (close - center) / deviation
                if z_score <= -self.entry_z:
                    target = Decimal(1)
                elif z_score >= self.entry_z:
                    target = Decimal(-1)
                elif abs(z_score) < 0.25:
                    target = Decimal(0)
        self.closes.append(close)
        return target


class FuturesTrendBaseline(DonchianMomentumBaseline):
    strategy_id = "futures_diversified_trend_v1"


def generate_synthetic_bars(
    *,
    instrument_id: str,
    count: int = 96,
    profile: str = "trend",
    venue: str = "synthetic",
    asset_class: str = "crypto_spot",
) -> list[CanonicalEvent]:
    if count < 20:
        raise ValueError("synthetic baseline requires at least 20 bars")
    start = 1_704_067_200_000_000_000
    interval = 60_000_000_000
    price = Decimal("100")
    events = []
    for index in range(count):
        if profile == "trend":
            change = Decimal("0.35") if index % 13 else Decimal("-0.80")
        elif profile == "mean_reversion":
            change = Decimal((index % 8) - 4) / Decimal(20)
        elif profile == "flat":
            change = Decimal((index % 5) - 2) / Decimal(50)
        else:
            raise ValueError(f"unknown synthetic profile: {profile}")
        open_price = price
        close = max(Decimal("1"), open_price + change)
        high = max(open_price, close) + Decimal("0.10")
        low = min(open_price, close) - Decimal("0.10")
        timestamp = start + index * interval
        raw = {"index": index, "open": format(open_price, "f"), "close": format(close, "f")}
        events.append(
            CanonicalEvent.from_raw(
                raw=raw,
                source="the-pass-synthetic",
                venue=venue,
                asset_class=asset_class,
                instrument_id=instrument_id,
                event_type=EventType.BAR,
                event_time_ns=timestamp,
                receive_time_ns=timestamp + 1_000_000,
                ingest_id=f"{instrument_id}-bar-{index:04d}",
                sequence=index,
                payload={
                    "open": open_price,
                    "high": high,
                    "low": low,
                    "close": close,
                    "volume": Decimal(100 + index % 17),
                },
            )
        )
        price = close
    return events


def scan_prediction_complements(snapshots: Sequence[dict[str, Decimal]]) -> dict[str, object]:
    opportunities = []
    for index, snapshot in enumerate(snapshots):
        yes_ask = Decimal(snapshot["yes_ask"])
        no_ask = Decimal(snapshot["no_ask"])
        total = yes_ask + no_ask
        if total < Decimal(1):
            opportunities.append({"index": index, "ask_sum": format(total, "f"), "gross_edge": format(Decimal(1) - total, "f")})
    return {
        "strategy_id": "prediction_market_complement_or_fair_value_v1",
        "snapshots": len(snapshots),
        "opportunities": opportunities,
        "status": "diagnostic_only",
    }

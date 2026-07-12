"""Conservative reference fill models backed by subsequent market evidence."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from the_pass.data.contracts import CanonicalEvent, EventType

from .contracts import CostModel, Fill, FillOutcome, SimulatedIntent


def _levels(event: CanonicalEvent, side: str) -> list[tuple[Decimal, Decimal]]:
    field = "asks" if side == "buy" else "bids"
    rows = [(Decimal(str(price)), Decimal(str(size))) for price, size in event.payload.get(field, [])]
    if any(not price.is_finite() or price <= 0 or not size.is_finite() or size <= 0 for price, size in rows):
        raise ValueError("book levels must contain positive finite prices and sizes")
    return sorted(rows, key=lambda row: row[0], reverse=side == "sell")


def _mid(event: CanonicalEvent) -> Decimal | None:
    bids = _levels(event, "sell")
    asks = _levels(event, "buy")
    if not bids or not asks:
        return None
    return (bids[0][0] + asks[0][0]) / Decimal(2)


@dataclass(frozen=True)
class MarketDepthFillModel:
    promotion_eligible: bool = True

    def evaluate(self, intent: SimulatedIntent, event: CanonicalEvent, cost_model: CostModel) -> FillOutcome:
        if intent.intent_type != "market" or event.instrument_id != intent.instrument_id:
            return FillOutcome(remaining_quantity=intent.quantity)
        if event.receive_time_ns <= intent.decision_time_ns or event.event_type != EventType.BOOK_SNAPSHOT:
            return FillOutcome(remaining_quantity=intent.quantity)
        remaining = intent.quantity
        fills = []
        reference_mid = _mid(event)
        for price, available in _levels(event, intent.side):
            if remaining <= 0:
                break
            quantity = min(available, remaining)
            costs = cost_model.costs(intent, price, quantity, reference_mid=reference_mid)
            fills.append(
                Fill(
                    intent_id=intent.intent_id,
                    instrument_id=intent.instrument_id,
                    side=intent.side,
                    quantity=quantity,
                    price=price,
                    event_time_ns=event.receive_time_ns,
                    fee=costs["fee"],
                    spread_cost=costs["spread"],
                    slippage_cost=costs["slippage"],
                    evidence=f"book_snapshot:{event.ingest_id}",
                )
            )
            remaining -= quantity
        status = "filled" if remaining == 0 else "partial_rejected" if fills else "rejected"
        reason = "" if remaining == 0 else "insufficient opposing depth"
        return FillOutcome(tuple(fills), remaining, status, reason)


@dataclass(frozen=True)
class LimitEvidenceFillModel:
    queue_haircut: Decimal = Decimal("0.5")
    adverse_selection_haircut: Decimal = Decimal("0.75")
    promotion_eligible: bool = True

    def __post_init__(self) -> None:
        for value in (self.queue_haircut, self.adverse_selection_haircut):
            if not value.is_finite() or value < 0 or value > 1:
                raise ValueError("fill haircuts must be between zero and one")

    def evaluate(self, intent: SimulatedIntent, event: CanonicalEvent, cost_model: CostModel) -> FillOutcome:
        if intent.intent_type != "limit" or event.instrument_id != intent.instrument_id:
            return FillOutcome(remaining_quantity=intent.quantity)
        if event.receive_time_ns <= intent.decision_time_ns:
            return FillOutcome(remaining_quantity=intent.quantity)
        price = None
        available = Decimal(0)
        if event.event_type == EventType.TRADE:
            trade_price = Decimal(str(event.payload["price"]))
            crossed = trade_price <= intent.limit_price if intent.side == "buy" else trade_price >= intent.limit_price
            if crossed:
                price = intent.limit_price
                available = Decimal(str(event.payload["size"]))
        elif event.event_type in {EventType.BOOK_SNAPSHOT, EventType.BOOK_DELTA}:
            levels = _levels(event, intent.side)
            eligible = [level for level in levels if level[0] <= intent.limit_price] if intent.side == "buy" else [level for level in levels if level[0] >= intent.limit_price]
            if eligible:
                price = intent.limit_price
                available = sum((size for _level_price, size in eligible), Decimal(0))
        if price is None:
            return FillOutcome(remaining_quantity=intent.quantity)
        quantity = min(intent.quantity, available * self.queue_haircut * self.adverse_selection_haircut)
        if quantity <= 0:
            return FillOutcome(remaining_quantity=intent.quantity, status="missed", reason="queue and adverse-selection haircut")
        costs = cost_model.costs(intent, price, quantity, reference_mid=_mid(event) if event.event_type != EventType.TRADE else None)
        fill = Fill(
            intent_id=intent.intent_id,
            instrument_id=intent.instrument_id,
            side=intent.side,
            quantity=quantity,
            price=price,
            event_time_ns=event.receive_time_ns,
            fee=costs["fee"],
            spread_cost=costs["spread"],
            slippage_cost=costs["slippage"],
            evidence=f"subsequent_{event.event_type.value}:{event.ingest_id}",
        )
        remaining = intent.quantity - quantity
        return FillOutcome((fill,), remaining, "filled" if remaining == 0 else "partial", "")


@dataclass(frozen=True)
class BarFillModel:
    slippage_bps: Decimal = Decimal("5")
    promotion_eligible: bool = True

    def __post_init__(self) -> None:
        if not self.slippage_bps.is_finite() or self.slippage_bps < 0:
            raise ValueError("slippage_bps must be non-negative and finite")

    def evaluate(self, intent: SimulatedIntent, event: CanonicalEvent, cost_model: CostModel) -> FillOutcome:
        if intent.intent_type != "bar" or event.instrument_id != intent.instrument_id:
            return FillOutcome(remaining_quantity=intent.quantity)
        if event.receive_time_ns <= intent.decision_time_ns or event.event_type != EventType.BAR:
            return FillOutcome(remaining_quantity=intent.quantity)
        open_price = Decimal(str(event.payload["open"]))
        direction = Decimal(1) if intent.side == "buy" else Decimal(-1)
        price = open_price * (Decimal(1) + direction * self.slippage_bps / Decimal(10_000))
        costs = cost_model.costs(intent, price, intent.quantity, reference_mid=open_price)
        slippage = abs(price - open_price) * intent.quantity
        fill = Fill(
            intent_id=intent.intent_id,
            instrument_id=intent.instrument_id,
            side=intent.side,
            quantity=intent.quantity,
            price=price,
            event_time_ns=event.receive_time_ns,
            fee=costs["fee"],
            spread_cost=Decimal(0),
            slippage_cost=slippage,
            evidence=f"next_bar_open:{event.ingest_id}",
        )
        return FillOutcome((fill,), Decimal(0), "filled", "")


@dataclass(frozen=True)
class DiagnosticMidpointFillModel:
    promotion_eligible: bool = False

    def evaluate(self, intent: SimulatedIntent, event: CanonicalEvent, cost_model: CostModel) -> FillOutcome:
        if (
            intent.intent_type != "mid_diagnostic"
            or event.instrument_id != intent.instrument_id
            or event.event_type not in {EventType.BOOK_SNAPSHOT, EventType.BOOK_DELTA}
            or event.receive_time_ns <= intent.decision_time_ns
        ):
            return FillOutcome(remaining_quantity=intent.quantity, promotion_eligible=False)
        midpoint = _mid(event)
        if midpoint is None:
            return FillOutcome(remaining_quantity=intent.quantity, promotion_eligible=False)
        costs = cost_model.costs(intent, midpoint, intent.quantity, reference_mid=midpoint)
        fill = Fill(
            intent.intent_id,
            intent.instrument_id,
            intent.side,
            intent.quantity,
            midpoint,
            event.receive_time_ns,
            costs["fee"],
            Decimal(0),
            Decimal(0),
            f"diagnostic_midpoint:{event.ingest_id}",
        )
        return FillOutcome((fill,), Decimal(0), "filled", "diagnostic midpoint cannot support promotion", False)

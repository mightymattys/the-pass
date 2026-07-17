"""Conservative reference fill models backed by subsequent market evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
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
    minimum_latency_ns: int = 0
    participation_rate: Decimal = Decimal(1)
    promotion_eligible: bool = True

    def __post_init__(self) -> None:
        if self.minimum_latency_ns < 0:
            raise ValueError("minimum_latency_ns must be non-negative")
        if (
            not self.participation_rate.is_finite()
            or self.participation_rate <= 0
            or self.participation_rate > 1
        ):
            raise ValueError("participation_rate must be in (0, 1]")

    def evaluate(self, intent: SimulatedIntent, event: CanonicalEvent, cost_model: CostModel) -> FillOutcome:
        if intent.intent_type != "market" or event.instrument_id != intent.instrument_id:
            return FillOutcome(remaining_quantity=intent.quantity)
        if (
            event.receive_time_ns
            <= intent.decision_time_ns + self.minimum_latency_ns
            or event.event_type != EventType.BOOK_SNAPSHOT
        ):
            return FillOutcome(remaining_quantity=intent.quantity)
        remaining = intent.quantity
        fills = []
        reference_mid = _mid(event)
        for price, available in _levels(event, intent.side):
            if remaining <= 0:
                break
            quantity = min(available * self.participation_rate, remaining)
            costs = cost_model.costs(
                intent,
                price,
                quantity,
                reference_mid=reference_mid,
                event=event,
            )
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
                    impact_cost=costs.get("impact", Decimal(0)),
                    latency_ns=event.receive_time_ns - intent.decision_time_ns,
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
    minimum_latency_ns: int = 0
    participation_rate: Decimal = Decimal(1)
    promotion_eligible: bool = True

    def __post_init__(self) -> None:
        for value in (self.queue_haircut, self.adverse_selection_haircut):
            if not value.is_finite() or value < 0 or value > 1:
                raise ValueError("fill haircuts must be between zero and one")
        if self.minimum_latency_ns < 0:
            raise ValueError("minimum_latency_ns must be non-negative")
        if (
            not self.participation_rate.is_finite()
            or self.participation_rate <= 0
            or self.participation_rate > 1
        ):
            raise ValueError("participation_rate must be in (0, 1]")

    def evaluate(self, intent: SimulatedIntent, event: CanonicalEvent, cost_model: CostModel) -> FillOutcome:
        if intent.intent_type != "limit" or event.instrument_id != intent.instrument_id:
            return FillOutcome(remaining_quantity=intent.quantity)
        if (
            event.receive_time_ns
            <= intent.decision_time_ns + self.minimum_latency_ns
        ):
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
        quantity = min(
            intent.quantity,
            available
            * self.participation_rate
            * self.queue_haircut
            * self.adverse_selection_haircut,
        )
        if quantity <= 0:
            return FillOutcome(remaining_quantity=intent.quantity, status="missed", reason="queue and adverse-selection haircut")
        costs = cost_model.costs(
            intent,
            price,
            quantity,
            reference_mid=(
                _mid(event) if event.event_type != EventType.TRADE else None
            ),
            event=event,
        )
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
            impact_cost=costs.get("impact", Decimal(0)),
            latency_ns=event.receive_time_ns - intent.decision_time_ns,
        )
        remaining = intent.quantity - quantity
        return FillOutcome((fill,), remaining, "filled" if remaining == 0 else "partial", "")


@dataclass
class BarFillModel:
    """Fill at the next bar open, capped to a share of reported bar volume."""

    slippage_bps: Decimal = Decimal("5")
    minimum_latency_ns: int = 0
    participation_rate: Decimal = Decimal("0.10")
    promotion_eligible: bool = True
    _budget_event_key: tuple[object, ...] | None = field(
        default=None, init=False, repr=False, compare=False
    )
    _remaining_participation: Decimal = field(
        default=Decimal(0), init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if not self.slippage_bps.is_finite() or self.slippage_bps < 0:
            raise ValueError("slippage_bps must be non-negative and finite")
        if self.minimum_latency_ns < 0:
            raise ValueError("minimum_latency_ns must be non-negative")
        if (
            not self.participation_rate.is_finite()
            or self.participation_rate <= 0
            or self.participation_rate > 1
        ):
            raise ValueError("participation_rate must be in (0, 1]")

    @staticmethod
    def _event_key(event: CanonicalEvent) -> tuple[object, ...]:
        return (
            event.instrument_id,
            event.event_time_ns,
            event.receive_time_ns,
            event.ingest_id,
        )

    def begin_event(self, event: CanonicalEvent) -> None:
        """Reset the shared participation budget for one simulator event."""

        self._budget_event_key = self._event_key(event)
        raw_volume = event.payload.get("volume")
        self._remaining_participation = (
            Decimal(str(raw_volume)) * self.participation_rate
            if event.event_type == EventType.BAR and raw_volume is not None
            else Decimal(0)
        )

    def _ensure_event_budget(self, event: CanonicalEvent) -> None:
        if self._budget_event_key != self._event_key(event):
            self.begin_event(event)

    def evaluate(self, intent: SimulatedIntent, event: CanonicalEvent, cost_model: CostModel) -> FillOutcome:
        if intent.intent_type != "bar" or event.instrument_id != intent.instrument_id:
            return FillOutcome(remaining_quantity=intent.quantity)
        if (
            event.receive_time_ns
            <= intent.decision_time_ns + self.minimum_latency_ns
            or event.event_type != EventType.BAR
        ):
            return FillOutcome(remaining_quantity=intent.quantity)
        raw_volume = event.payload.get("volume")
        if raw_volume is None:
            return FillOutcome(
                remaining_quantity=intent.quantity,
                reason="bar volume is missing",
            )
        volume = Decimal(str(raw_volume))
        if not volume.is_finite() or volume < 0:
            raise ValueError("bar volume must be non-negative and finite")
        if volume == 0:
            return FillOutcome(
                remaining_quantity=intent.quantity,
                reason="bar volume is zero",
            )
        self._ensure_event_budget(event)
        quantity = min(intent.quantity, self._remaining_participation)
        if quantity == 0:
            return FillOutcome(
                remaining_quantity=intent.quantity,
                reason="bar participation cap",
            )
        self._remaining_participation -= quantity
        open_price = Decimal(str(event.payload["open"]))
        direction = Decimal(1) if intent.side == "buy" else Decimal(-1)
        price = open_price * (Decimal(1) + direction * self.slippage_bps / Decimal(10_000))
        costs = cost_model.costs(
            intent,
            price,
            quantity,
            reference_mid=open_price,
            event=event,
        )
        slippage = abs(price - open_price) * quantity
        fill = Fill(
            intent_id=intent.intent_id,
            instrument_id=intent.instrument_id,
            side=intent.side,
            quantity=quantity,
            price=price,
            event_time_ns=event.receive_time_ns,
            fee=costs["fee"],
            spread_cost=Decimal(0),
            slippage_cost=slippage,
            evidence=f"next_bar_open:{event.ingest_id}",
            impact_cost=costs.get("impact", Decimal(0)),
            latency_ns=event.receive_time_ns - intent.decision_time_ns,
        )
        remaining = intent.quantity - quantity
        return FillOutcome(
            (fill,),
            remaining,
            "filled" if remaining == 0 else "partial",
            "" if remaining == 0 else "bar participation cap",
        )


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
        costs = cost_model.costs(
            intent,
            midpoint,
            intent.quantity,
            reference_mid=midpoint,
            event=event,
        )
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

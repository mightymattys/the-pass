"""Engine-neutral strategy, fill, cost, portfolio, and risk interfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Mapping, Protocol, Sequence

from the_pass.data.contracts import CanonicalEvent


@dataclass(frozen=True)
class SimulatedIntent:
    intent_id: str
    instrument_id: str
    side: str
    quantity: Decimal
    decision_time_ns: int
    intent_type: str
    limit_price: Decimal | None = None

    def __post_init__(self) -> None:
        if self.side not in {"buy", "sell"}:
            raise ValueError("side must be buy or sell")
        if not self.quantity.is_finite() or self.quantity <= 0:
            raise ValueError("quantity must be positive and finite")
        if self.intent_type not in {"market", "limit", "bar", "mid_diagnostic"}:
            raise ValueError("unsupported simulated intent type")
        if self.intent_type == "limit" and self.limit_price is None:
            raise ValueError("limit intent requires limit_price")


@dataclass(frozen=True)
class Fill:
    intent_id: str
    instrument_id: str
    side: str
    quantity: Decimal
    price: Decimal
    event_time_ns: int
    fee: Decimal = Decimal(0)
    spread_cost: Decimal = Decimal(0)
    slippage_cost: Decimal = Decimal(0)
    evidence: str = ""


@dataclass(frozen=True)
class FillOutcome:
    fills: tuple[Fill, ...] = ()
    remaining_quantity: Decimal = Decimal(0)
    status: str = "pending"
    reason: str = ""
    promotion_eligible: bool = True


@dataclass(frozen=True)
class RunnerContext:
    event_index: int
    total_events: int
    decision_time_ns: int
    positions: Mapping[str, Decimal]
    marks: Mapping[str, Decimal]


@dataclass
class RunnerResult:
    strategy_id: str
    events_processed: int
    signals: int
    intents: list[SimulatedIntent]
    fills: list[Fill]
    rejected: list[dict[str, Any]]
    missed: list[dict[str, Any]]
    equity_curve: list[dict[str, Any]]
    cost_components: dict[str, Decimal]
    final_snapshot: dict[str, Any]
    diagnostics: dict[str, Any] = field(default_factory=dict)


class StrategyRunner(Protocol):
    strategy_id: str

    def on_event(self, event: CanonicalEvent, context: RunnerContext) -> Sequence[SimulatedIntent]: ...


class FeatureProvider(Protocol):
    def features_at(self, event: CanonicalEvent, decision_time_ns: int) -> Mapping[str, Any]: ...


class CostModel(Protocol):
    def costs(self, intent: SimulatedIntent, price: Decimal, quantity: Decimal, *, reference_mid: Decimal | None) -> dict[str, Decimal]: ...


class FillModel(Protocol):
    promotion_eligible: bool

    def evaluate(self, intent: SimulatedIntent, event: CanonicalEvent, cost_model: CostModel) -> FillOutcome: ...


class Portfolio(Protocol):
    @property
    def positions(self) -> Mapping[str, Decimal]: ...

    def apply_fill(self, fill: Fill) -> None: ...

    def mark(self, instrument_id: str, price: Decimal, event_time_ns: int) -> dict[str, Any]: ...


class RiskPolicy(Protocol):
    def allow(self, intent: SimulatedIntent, portfolio: Portfolio) -> tuple[bool, str]: ...

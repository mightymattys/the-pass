"""Double-entry-like portfolio accounting with per-event conservation checks."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping

from .contracts import Fill


@dataclass
class PositionState:
    quantity: Decimal = Decimal(0)
    average_price: Decimal = Decimal(0)


@dataclass(frozen=True)
class InstrumentAccounting:
    instrument_type: str = "spot"
    multiplier: Decimal = Decimal(1)

    def __post_init__(self) -> None:
        if self.instrument_type not in {"spot", "prediction", "future"}:
            raise ValueError("instrument_type must be spot, prediction, or future")
        if not self.multiplier.is_finite() or self.multiplier <= 0:
            raise ValueError("instrument multiplier must be positive and finite")


class AccountingPortfolio:
    def __init__(self, initial_cash: Decimal, *, collateral: Decimal = Decimal(0)) -> None:
        if not initial_cash.is_finite() or initial_cash <= 0:
            raise ValueError("initial_cash must be positive and finite")
        self.initial_cash = initial_cash
        self.cash = initial_cash
        if not collateral.is_finite() or collateral < 0:
            raise ValueError("collateral must be non-negative and finite")
        self.collateral = collateral
        self._positions: dict[str, PositionState] = {}
        self._instruments: dict[str, InstrumentAccounting] = {}
        self.marks: dict[str, Decimal] = {}
        self.realized_pnl = Decimal(0)
        self.fees = Decimal(0)
        self.impact = Decimal(0)
        self.funding = Decimal(0)
        self.borrow = Decimal(0)
        self.roll = Decimal(0)
        self.opportunity_cost = Decimal(0)
        self.rejected_notional = Decimal(0)
        self.daily_start_equity = initial_cash
        self._utc_day: int | None = None

    @property
    def positions(self) -> Mapping[str, Decimal]:
        return {instrument: state.quantity for instrument, state in self._positions.items()}

    @property
    def instrument_multipliers(self) -> Mapping[str, Decimal]:
        return {
            instrument: metadata.multiplier
            for instrument, metadata in self._instruments.items()
        }

    def register_instrument(
        self,
        instrument_id: str,
        *,
        instrument_type: str,
        multiplier: Decimal,
    ) -> None:
        if not instrument_id:
            raise ValueError("instrument_id must not be empty")
        metadata = InstrumentAccounting(instrument_type, multiplier)
        existing = self._instruments.get(instrument_id)
        if existing is not None and existing != metadata:
            raise ValueError("instrument accounting metadata changed during replay")
        self._instruments[instrument_id] = metadata

    def instrument_accounting(self, instrument_id: str) -> InstrumentAccounting:
        return self._instruments.get(instrument_id, InstrumentAccounting())

    def apply_fill(self, fill: Fill) -> None:
        direction = Decimal(1) if fill.side == "buy" else Decimal(-1)
        delta = direction * fill.quantity
        state = self._positions.setdefault(fill.instrument_id, PositionState())
        metadata = self.instrument_accounting(fill.instrument_id)
        old_quantity = state.quantity
        realized_change = Decimal(0)
        if old_quantity == 0 or old_quantity * delta > 0:
            total = abs(old_quantity) + abs(delta)
            state.average_price = (abs(old_quantity) * state.average_price + abs(delta) * fill.price) / total
        else:
            closing = min(abs(old_quantity), abs(delta))
            old_sign = Decimal(1) if old_quantity > 0 else Decimal(-1)
            realized_change = (
                closing
                * (fill.price - state.average_price)
                * old_sign
                * metadata.multiplier
            )
            self.realized_pnl += realized_change
            if abs(delta) > abs(old_quantity):
                state.average_price = fill.price
            elif abs(delta) == abs(old_quantity):
                state.average_price = Decimal(0)
        state.quantity = old_quantity + delta
        if metadata.instrument_type == "future":
            self.cash += realized_change - fill.fee - fill.impact_cost
        else:
            self.cash -= (
                delta * fill.price * metadata.multiplier
                + fill.fee
                + fill.impact_cost
            )
        self.fees += fill.fee
        self.impact += fill.impact_cost
        self.marks[fill.instrument_id] = fill.price
        self.assert_conservation()

    def apply_carry_cost(self, component: str, amount: Decimal) -> None:
        if (
            component not in {"funding", "borrow", "roll"}
            or not amount.is_finite()
            or component in {"borrow", "roll"}
            and amount < 0
        ):
            raise ValueError("invalid carry cost")
        setattr(self, component, getattr(self, component) + amount)
        self.cash -= amount
        self.assert_conservation()

    def apply_funding_rate(
        self,
        instrument_id: str,
        *,
        rate: Decimal,
        price: Decimal | None = None,
    ) -> Decimal:
        if not rate.is_finite():
            raise ValueError("funding rate must be finite")
        state = self._positions.get(instrument_id, PositionState())
        mark = price or self.marks.get(instrument_id)
        if mark is None or not mark.is_finite() or mark <= 0:
            raise ValueError("funding requires a positive finite mark")
        metadata = self.instrument_accounting(instrument_id)
        amount = state.quantity * mark * metadata.multiplier * rate
        self.apply_carry_cost("funding", amount)
        return amount

    def settle_position(
        self, instrument_id: str, settlement_price: Decimal
    ) -> Decimal:
        if not settlement_price.is_finite() or settlement_price < 0:
            raise ValueError("settlement price must be non-negative and finite")
        state = self._positions.get(instrument_id)
        if state is None or state.quantity == 0:
            self.marks[instrument_id] = settlement_price
            return Decimal(0)
        metadata = self.instrument_accounting(instrument_id)
        realized_change = (
            state.quantity
            * (settlement_price - state.average_price)
            * metadata.multiplier
        )
        if metadata.instrument_type == "future":
            self.cash += realized_change
        else:
            self.cash += (
                state.quantity * settlement_price * metadata.multiplier
            )
        self.realized_pnl += realized_change
        state.quantity = Decimal(0)
        state.average_price = Decimal(0)
        self.marks[instrument_id] = settlement_price
        self.assert_conservation()
        return realized_change

    def begin_event(self, event_time_ns: int) -> None:
        if not isinstance(event_time_ns, int) or isinstance(event_time_ns, bool) or event_time_ns < 0:
            raise ValueError("event_time_ns must be non-negative UTC nanoseconds")
        utc_day = event_time_ns // 86_400_000_000_000
        if self._utc_day != utc_day:
            self._utc_day = utc_day
            self.daily_start_equity = self.equity()

    def mark(self, instrument_id: str, price: Decimal, event_time_ns: int) -> dict[str, Any]:
        if price <= 0 or not price.is_finite():
            raise ValueError("mark price must be positive and finite")
        self.begin_event(event_time_ns)
        self.marks[instrument_id] = price
        self.assert_conservation()
        return self.snapshot(event_time_ns)

    def unrealized_pnl(self) -> Decimal:
        return sum(
            (
                state.quantity
                * (
                    self.marks.get(instrument, state.average_price)
                    - state.average_price
                )
                * self.instrument_accounting(instrument).multiplier
                for instrument, state in self._positions.items()
            ),
            Decimal(0),
        )

    def equity(self) -> Decimal:
        inventory = sum(
            (
                state.quantity
                * self.marks.get(instrument, state.average_price)
                * self.instrument_accounting(instrument).multiplier
                if self.instrument_accounting(instrument).instrument_type
                != "future"
                else state.quantity
                * (
                    self.marks.get(instrument, state.average_price)
                    - state.average_price
                )
                * self.instrument_accounting(instrument).multiplier
                for instrument, state in self._positions.items()
            ),
            Decimal(0),
        )
        return self.cash + inventory

    def assert_conservation(self) -> None:
        expected = (
            self.initial_cash
            + self.realized_pnl
            + self.unrealized_pnl()
            - self.fees
            - self.impact
            - self.funding
            - self.borrow
            - self.roll
        )
        if self.equity() != expected:
            raise AssertionError(f"portfolio conservation failed: equity={self.equity()} expected={expected}")

    def snapshot(self, event_time_ns: int) -> dict[str, Any]:
        return {
            "event_time_ns": event_time_ns,
            "cash": self.cash,
            "collateral": self.collateral,
            "equity": self.equity(),
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl(),
            "fees": self.fees,
            "impact": self.impact,
            "funding": self.funding,
            "borrow": self.borrow,
            "roll": self.roll,
            "opportunity_cost": self.opportunity_cost,
            "positions": dict(self.positions),
        }

    def export_state(self) -> dict[str, Any]:
        return {
            "initial_cash": format(self.initial_cash, "f"),
            "cash": format(self.cash, "f"),
            "collateral": format(self.collateral, "f"),
            "positions": {
                instrument: {
                    "quantity": format(state.quantity, "f"),
                    "average_price": format(state.average_price, "f"),
                }
                for instrument, state in sorted(self._positions.items())
            },
            "instruments": {
                instrument: {
                    "instrument_type": metadata.instrument_type,
                    "multiplier": format(metadata.multiplier, "f"),
                }
                for instrument, metadata in sorted(self._instruments.items())
            },
            "marks": {
                instrument: format(mark, "f")
                for instrument, mark in sorted(self.marks.items())
            },
            "realized_pnl": format(self.realized_pnl, "f"),
            "fees": format(self.fees, "f"),
            "impact": format(self.impact, "f"),
            "funding": format(self.funding, "f"),
            "borrow": format(self.borrow, "f"),
            "roll": format(self.roll, "f"),
            "opportunity_cost": format(self.opportunity_cost, "f"),
            "rejected_notional": format(self.rejected_notional, "f"),
            "daily_start_equity": format(self.daily_start_equity, "f"),
            "utc_day": self._utc_day,
        }

    @classmethod
    def from_state(cls, document: Mapping[str, Any]) -> "AccountingPortfolio":
        portfolio = cls(
            Decimal(str(document["initial_cash"])),
            collateral=Decimal(str(document["collateral"])),
        )
        portfolio.cash = Decimal(str(document["cash"]))
        portfolio._positions = {
            instrument: PositionState(
                Decimal(str(row["quantity"])),
                Decimal(str(row["average_price"])),
            )
            for instrument, row in document["positions"].items()
        }
        portfolio._instruments = {
            instrument: InstrumentAccounting(
                str(row["instrument_type"]),
                Decimal(str(row["multiplier"])),
            )
            for instrument, row in document["instruments"].items()
        }
        portfolio.marks = {
            instrument: Decimal(str(mark))
            for instrument, mark in document["marks"].items()
        }
        for field in (
            "realized_pnl",
            "fees",
            "impact",
            "funding",
            "borrow",
            "roll",
            "opportunity_cost",
            "rejected_notional",
            "daily_start_equity",
        ):
            setattr(portfolio, field, Decimal(str(document[field])))
        utc_day = document.get("utc_day")
        portfolio._utc_day = int(utc_day) if utc_day is not None else None
        portfolio.assert_conservation()
        return portfolio

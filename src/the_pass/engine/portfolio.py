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


class AccountingPortfolio:
    def __init__(self, initial_cash: Decimal, *, collateral: Decimal = Decimal(0)) -> None:
        if not initial_cash.is_finite() or initial_cash <= 0:
            raise ValueError("initial_cash must be positive and finite")
        self.initial_cash = initial_cash
        self.cash = initial_cash
        self.collateral = collateral
        self._positions: dict[str, PositionState] = {}
        self.marks: dict[str, Decimal] = {}
        self.realized_pnl = Decimal(0)
        self.fees = Decimal(0)
        self.funding = Decimal(0)
        self.borrow = Decimal(0)
        self.roll = Decimal(0)
        self.opportunity_cost = Decimal(0)
        self.rejected_notional = Decimal(0)

    @property
    def positions(self) -> Mapping[str, Decimal]:
        return {instrument: state.quantity for instrument, state in self._positions.items()}

    def apply_fill(self, fill: Fill) -> None:
        direction = Decimal(1) if fill.side == "buy" else Decimal(-1)
        delta = direction * fill.quantity
        state = self._positions.setdefault(fill.instrument_id, PositionState())
        old_quantity = state.quantity
        if old_quantity == 0 or old_quantity * delta > 0:
            total = abs(old_quantity) + abs(delta)
            state.average_price = (abs(old_quantity) * state.average_price + abs(delta) * fill.price) / total
        else:
            closing = min(abs(old_quantity), abs(delta))
            old_sign = Decimal(1) if old_quantity > 0 else Decimal(-1)
            self.realized_pnl += closing * (fill.price - state.average_price) * old_sign
            if abs(delta) > abs(old_quantity):
                state.average_price = fill.price
            elif abs(delta) == abs(old_quantity):
                state.average_price = Decimal(0)
        state.quantity = old_quantity + delta
        self.cash -= delta * fill.price + fill.fee
        self.fees += fill.fee
        self.marks[fill.instrument_id] = fill.price
        self.assert_conservation()

    def apply_carry_cost(self, component: str, amount: Decimal) -> None:
        if component not in {"funding", "borrow", "roll"} or amount < 0 or not amount.is_finite():
            raise ValueError("invalid carry cost")
        setattr(self, component, getattr(self, component) + amount)
        self.cash -= amount
        self.assert_conservation()

    def mark(self, instrument_id: str, price: Decimal, event_time_ns: int) -> dict[str, Any]:
        if price <= 0 or not price.is_finite():
            raise ValueError("mark price must be positive and finite")
        self.marks[instrument_id] = price
        self.assert_conservation()
        return self.snapshot(event_time_ns)

    def unrealized_pnl(self) -> Decimal:
        return sum(
            (
                state.quantity * (self.marks.get(instrument, state.average_price) - state.average_price)
                for instrument, state in self._positions.items()
            ),
            Decimal(0),
        )

    def equity(self) -> Decimal:
        inventory = sum(
            (state.quantity * self.marks.get(instrument, state.average_price) for instrument, state in self._positions.items()),
            Decimal(0),
        )
        return self.cash + inventory

    def assert_conservation(self) -> None:
        expected = (
            self.initial_cash
            + self.realized_pnl
            + self.unrealized_pnl()
            - self.fees
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
            "funding": self.funding,
            "borrow": self.borrow,
            "roll": self.roll,
            "opportunity_cost": self.opportunity_cost,
            "positions": dict(self.positions),
        }

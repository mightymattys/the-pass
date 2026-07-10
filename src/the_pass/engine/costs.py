"""Explicit deterministic transaction-cost models."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .contracts import SimulatedIntent


@dataclass(frozen=True)
class LinearCostModel:
    fee_rate: Decimal = Decimal("0.001")

    def __post_init__(self) -> None:
        if not self.fee_rate.is_finite() or self.fee_rate < 0:
            raise ValueError("fee_rate must be non-negative and finite")

    def costs(
        self,
        intent: SimulatedIntent,
        price: Decimal,
        quantity: Decimal,
        *,
        reference_mid: Decimal | None,
    ) -> dict[str, Decimal]:
        notional = abs(price * quantity)
        fee = notional * self.fee_rate
        spread = Decimal(0)
        if reference_mid is not None:
            spread = abs(price - reference_mid) * quantity
        return {"fee": fee, "spread": spread, "slippage": Decimal(0)}

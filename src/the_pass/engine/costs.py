"""Explicit deterministic transaction-cost models."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from the_pass.data.contracts import CanonicalEvent

from .contracts import SimulatedIntent


@dataclass(frozen=True)
class LinearCostModel:
    """Costs relative to a mid-execution gross-PnL baseline."""

    fee_rate: Decimal = Decimal("0.001")
    impact_bps: Decimal = Decimal(0)

    def __post_init__(self) -> None:
        if (
            not self.fee_rate.is_finite()
            or self.fee_rate < 0
            or not self.impact_bps.is_finite()
            or self.impact_bps < 0
        ):
            raise ValueError("fee_rate and impact_bps must be non-negative and finite")

    def costs(
        self,
        intent: SimulatedIntent,
        price: Decimal,
        quantity: Decimal,
        *,
        reference_mid: Decimal | None,
        event: CanonicalEvent | None = None,
    ) -> dict[str, Decimal]:
        notional = abs(price * quantity)
        effective_fee_rate = self.fee_rate
        if event is not None and "fee_rate" in event.payload:
            observed = Decimal(str(event.payload["fee_rate"]))
            if not observed.is_finite() or observed < 0:
                raise ValueError("event fee_rate must be non-negative and finite")
            effective_fee_rate = observed
        fee = notional * effective_fee_rate
        spread = Decimal(0)
        if reference_mid is not None:
            direction = Decimal(1) if intent.side == "buy" else Decimal(-1)
            spread = max(
                Decimal(0), direction * (price - reference_mid) * quantity
            )
        impact = notional * self.impact_bps / Decimal(10_000)
        return {
            "fee": fee,
            "spread": spread,
            "slippage": Decimal(0),
            "impact": impact,
        }

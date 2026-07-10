"""Versioned deterministic cost, liquidity, and operational stress scenarios."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class StressParameters:
    gross_pnl: Decimal
    fees: Decimal
    slippage: Decimal
    funding: Decimal = Decimal(0)
    missed_fill_cost: Decimal = Decimal(0)
    outage_loss: Decimal = Decimal(0)
    gap_loss: Decimal = Decimal(0)
    deleverage_loss: Decimal = Decimal(0)


def run_stress_suite(parameters: StressParameters) -> list[dict[str, Any]]:
    scenarios = (
        ("fees_x1_5", Decimal("1.5"), Decimal(1), Decimal(1), Decimal(1), Decimal(0)),
        ("slippage_x2", Decimal(1), Decimal(2), Decimal(1), Decimal(1), Decimal(0)),
        ("latency_x2", Decimal(1), Decimal("1.5"), Decimal(1), Decimal(1), parameters.missed_fill_cost),
        ("depth_x0_5", Decimal(1), Decimal(2), Decimal(1), Decimal(1), parameters.missed_fill_cost),
        ("depth_x0_25", Decimal(1), Decimal(4), Decimal(1), Decimal(1), parameters.missed_fill_cost * 2),
        ("maker_fill_probability_x0_5", Decimal(1), Decimal(1), Decimal(1), Decimal(1), parameters.missed_fill_cost * 2),
        ("funding_worst_decile", Decimal(1), Decimal(1), Decimal(2), Decimal(1), Decimal(0)),
    )
    results = []
    for name, fee_multiple, slippage_multiple, funding_multiple, _fill_multiple, extra in scenarios:
        net = (
            parameters.gross_pnl
            - parameters.fees * fee_multiple
            - parameters.slippage * slippage_multiple
            - parameters.funding * funding_multiple
            - extra
        )
        results.append({"scenario": name, "net_pnl": float(net), "pass": net > 0})
    for name, loss in (
        ("exchange_outage", parameters.outage_loss),
        ("missing_interval", parameters.outage_loss),
        ("correlated_gap", parameters.gap_loss),
        ("forced_deleverage", parameters.deleverage_loss),
    ):
        net = parameters.gross_pnl - parameters.fees - parameters.slippage - parameters.funding - loss
        results.append({"scenario": name, "net_pnl": float(net), "pass": net > 0})
    return results

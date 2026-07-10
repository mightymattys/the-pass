"""NumPy/pandas reference screen runner for pre-registered parameter grids."""

from __future__ import annotations

import math
from decimal import Decimal
from typing import Any, Sequence


class ReferenceScreenRunner:
    def run(
        self,
        closes: Sequence[Decimal],
        *,
        family: str,
        variants: Sequence[dict[str, Any]],
        fee_bps: Decimal = Decimal("10"),
    ) -> list[dict[str, Any]]:
        try:
            import numpy as np
            import pandas as pd
        except ImportError as exc:
            raise RuntimeError("reference screens require the 'research' extra") from exc
        if len(closes) < 20:
            raise ValueError("reference screen requires at least 20 closes")
        if not variants:
            raise ValueError("screen variants must be preregistered")
        prices = pd.Series([float(value) for value in closes], dtype="float64")
        returns = prices.pct_change().fillna(0.0)
        results = []
        for variant_id, parameters in enumerate(variants):
            if family == "donchian":
                lookback = int(parameters["lookback"])
                upper = prices.shift(1).rolling(lookback).max()
                lower = prices.shift(1).rolling(lookback).min()
                signal = pd.Series(np.where(prices > upper, 1.0, np.where(prices < lower, -1.0, np.nan)))
                signal = signal.ffill().fillna(0.0)
            elif family == "mean_reversion":
                lookback = int(parameters["lookback"])
                entry_z = float(parameters["entry_z"])
                center = prices.shift(1).rolling(lookback).mean()
                deviation = prices.shift(1).rolling(lookback).std(ddof=0)
                z_score = (prices - center) / deviation.replace(0.0, np.nan)
                signal = pd.Series(np.where(z_score <= -entry_z, 1.0, np.where(z_score >= entry_z, -1.0, 0.0))).fillna(0.0)
            elif family == "random":
                generator = np.random.default_rng(int(parameters["seed"]))
                signal = pd.Series(generator.choice([-1.0, 0.0, 1.0], size=len(prices)))
            elif family == "buy_hold":
                signal = pd.Series(np.ones(len(prices)))
            else:
                raise ValueError(f"unsupported screen family: {family}")
            turnover = signal.diff().abs().fillna(signal.abs())
            gross = signal.shift(1).fillna(0.0) * returns
            costs = turnover * float(fee_bps / Decimal(10_000))
            net = gross - costs
            net_total = float(net.sum())
            volatility = float(net.std(ddof=0))
            sharpe = float(net.mean() / volatility * math.sqrt(252)) if volatility else None
            results.append(
                {
                    "variant_id": variant_id,
                    "parameters": dict(parameters),
                    "observations": len(prices),
                    "gross_return": float(gross.sum()),
                    "cost_return": float(costs.sum()),
                    "net_return": net_total,
                    "turnover": float(turnover.sum()),
                    "sharpe": sharpe,
                }
            )
        return results

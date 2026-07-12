"""Versioned strategy-independent risk policy and reporting."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from the_pass.data.contracts import stable_fingerprint
from the_pass.engine.contracts import Portfolio, SimulatedIntent


DEFAULT_POLICY_PATH = Path(__file__).resolve().parents[1] / "policies" / "risk-policies.v1.yaml"


def _load_policy(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not isinstance(document.get("asset_classes"), dict):
        raise ValueError("risk policy document is invalid")
    return document


def build_risk_policy_artifact(asset_class: str, *, path: Path = DEFAULT_POLICY_PATH) -> dict[str, Any]:
    document = _load_policy(path)
    if asset_class not in document["asset_classes"]:
        raise ValueError(f"unknown risk asset class: {asset_class}")
    created_at = document["created_at"]
    if isinstance(created_at, (date, datetime)):
        created_at = created_at.isoformat().replace("+00:00", "Z")
    core = {
        "schema_version": 2,
        "policy_id": f"{document['policy_version']}-{asset_class}",
        "policy_version": document["policy_version"],
        "created_at": created_at,
        "asset_class": asset_class,
        "sizing": document["global"]["sizing"],
        "limits": document["global"]["limits"],
        "stress": document["global"]["stress"],
        "promotion_thresholds": document["asset_classes"][asset_class],
    }
    return {**core, "policy_hash": stable_fingerprint(core)}


@dataclass(frozen=True)
class VersionedRiskPolicy:
    policy_id: str
    policy_hash: str
    max_position_units: Decimal
    max_notional: Decimal
    max_daily_loss: Decimal

    @classmethod
    def from_artifact(cls, artifact: Mapping[str, Any]) -> "VersionedRiskPolicy":
        core = {key: value for key, value in artifact.items() if key != "policy_hash"}
        if stable_fingerprint(core) != artifact.get("policy_hash"):
            raise ValueError("risk policy hash does not match policy contents")
        limits = artifact["limits"]
        return cls(
            policy_id=str(artifact["policy_id"]),
            policy_hash=str(artifact["policy_hash"]),
            max_position_units=Decimal(str(limits["max_position_units"])),
            max_notional=Decimal(str(limits["max_notional"])),
            max_daily_loss=Decimal(str(limits["max_daily_loss"])),
        )

    def allow(self, intent: SimulatedIntent, portfolio: Portfolio) -> tuple[bool, str]:
        direction = Decimal(1) if intent.side == "buy" else Decimal(-1)
        resulting = portfolio.positions.get(intent.instrument_id, Decimal(0)) + direction * intent.quantity
        if abs(resulting) > self.max_position_units:
            return False, "max_position_units"
        marks = getattr(portfolio, "marks", {})
        mark = marks.get(intent.instrument_id) or intent.limit_price
        if mark is None or not Decimal(mark).is_finite() or Decimal(mark) <= 0:
            return False, "missing_reference_price"
        if abs(resulting * Decimal(mark)) > self.max_notional:
            return False, "max_notional"
        daily_start_equity = getattr(portfolio, "daily_start_equity", None)
        equity = portfolio.equity() if hasattr(portfolio, "equity") else None
        if (
            daily_start_equity is None
            or equity is None
            or not Decimal(daily_start_equity).is_finite()
            or not Decimal(equity).is_finite()
        ):
            return False, "missing_daily_equity"
        if Decimal(daily_start_equity) - Decimal(equity) >= self.max_daily_loss:
            return False, "max_daily_loss"
        return True, ""

    def fixed_fraction_size(self, equity: Decimal, price: Decimal, fraction: Decimal) -> Decimal:
        if equity <= 0 or price <= 0 or fraction <= 0 or fraction > 1:
            raise ValueError("invalid fixed-fraction sizing inputs")
        return min(self.max_position_units, equity * fraction / price)

    def volatility_target_size(
        self,
        equity: Decimal,
        price: Decimal,
        annualized_volatility: Decimal,
        target_volatility: Decimal,
    ) -> Decimal:
        if min(equity, price, annualized_volatility, target_volatility) <= 0:
            raise ValueError("volatility sizing inputs must be positive")
        return min(self.max_position_units, equity * target_volatility / annualized_volatility / price)

    def kelly_upper_bound(self, win_probability: Decimal, payoff_ratio: Decimal) -> Decimal:
        if not (Decimal(0) < win_probability < Decimal(1)) or payoff_ratio <= 0:
            raise ValueError("invalid Kelly inputs")
        fraction = win_probability - (Decimal(1) - win_probability) / payoff_ratio
        return max(Decimal(0), fraction)


def _drawdowns(returns: Sequence[float]) -> list[float]:
    equity = 1.0
    peak = 1.0
    values = []
    for value in returns:
        equity *= 1 + float(value)
        peak = max(peak, equity)
        values.append((peak - equity) / peak)
    return values


def build_risk_report(
    *,
    package_id: str,
    policy: Mapping[str, Any],
    returns: Sequence[float],
    scenario_losses: Sequence[Mapping[str, Any]],
    capacity: float,
    blockers: Sequence[str],
) -> dict[str, Any]:
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("risk reports require the 'research' extra") from exc
    values = np.asarray(returns, dtype=float)
    if values.ndim != 1 or len(values) < 2 or not np.all(np.isfinite(values)):
        raise ValueError("risk report requires finite returns")
    sorted_returns = np.sort(values)
    tail = sorted_returns[: max(1, math.ceil(len(values) * 0.05))]
    drawdowns = _drawdowns(values)
    generator = np.random.default_rng(7)
    simulated_max_drawdowns = []
    ruin = 0
    for _ in range(500):
        path = generator.choice(values, size=len(values), replace=True)
        path_drawdown = max(_drawdowns(path), default=0.0)
        simulated_max_drawdowns.append(path_drawdown)
        if path_drawdown >= 0.5:
            ruin += 1
    window = min(5, len(values))
    rolling = [(index, float(values[index : index + window].sum())) for index in range(len(values) - window + 1)]
    worst = sorted(rolling, key=lambda item: item[1])[:3]
    return {
        "schema_version": 2,
        "id": f"risk-{package_id}",
        "created_at": "2026-07-10T00:00:00Z",
        "package_id": package_id,
        "policy_id": policy["policy_id"],
        "policy_hash": policy["policy_hash"],
        "sizing": {
            "default": policy["sizing"]["default"],
            "kelly_use": policy["sizing"]["kelly_use"],
        },
        "drawdown_distribution": {
            "observed_max": max(drawdowns, default=0.0),
            "bootstrap_median": float(np.median(simulated_max_drawdowns)),
            "bootstrap_p95": float(np.quantile(simulated_max_drawdowns, 0.95)),
        },
        "expected_shortfall": abs(float(tail.mean())),
        "risk_of_ruin_proxy": ruin / 500,
        "worst_windows": [{"start_index": index, "return": value} for index, value in worst],
        "exposure_correlation": {"single_series": 1.0},
        "scenario_losses": [dict(item) for item in scenario_losses],
        "capacity": {"diagnostic_notional": float(capacity), "method": "10x synthetic initial capital cap"},
        "blockers": list(blockers),
        "verdict": "blocked" if blockers else "pass",
    }

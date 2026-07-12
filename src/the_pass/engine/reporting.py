"""Metrics, cost waterfall, and static report rendering."""

from __future__ import annotations

import html
import math
from decimal import Decimal
from statistics import mean, median, pstdev
from typing import Any

from .contracts import RunnerResult


METRIC_NAMES = (
    "pnl",
    "total_return",
    "annualized_return",
    "volatility",
    "downside_volatility",
    "sharpe",
    "sortino",
    "calmar",
    "max_drawdown",
    "average_drawdown",
    "drawdown_duration",
    "win_rate",
    "payoff_ratio",
    "expectancy",
    "turnover",
    "average_holding_period",
    "expected_shortfall",
    "capacity_estimate",
)


def _safe_ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def _stable_metric(value: float | None) -> float | None:
    """Remove platform-level float noise before hashing public evidence."""

    if value is None:
        return None
    rounded = float(format(value, ".12g"))
    return 0.0 if rounded == 0 else rounded


def _metrics(
    result: RunnerResult,
    initial_cash: Decimal,
    pnl: Decimal,
    *,
    equities: list[float],
    periods_per_year: float,
) -> tuple[dict[str, float | None], dict[str, str]]:
    returns = [equities[index] / equities[index - 1] - 1 for index in range(1, len(equities)) if equities[index - 1]]
    total_return = float(pnl / initial_cash)
    annualized = None
    if returns and total_return > -1:
        try:
            annualized = math.expm1(math.log1p(total_return) * periods_per_year / len(returns))
        except OverflowError:
            annualized = None
    elif total_return == -1:
        annualized = -1.0
    volatility = pstdev(returns) * math.sqrt(periods_per_year) if len(returns) > 1 else None
    downside = [value for value in returns if value < 0]
    downside_volatility = pstdev(downside) * math.sqrt(periods_per_year) if len(downside) > 1 else None
    average_return = mean(returns) if returns else None
    sharpe = _safe_ratio(average_return * math.sqrt(periods_per_year), pstdev(returns)) if average_return is not None and len(returns) > 1 else None
    sortino = _safe_ratio(average_return * math.sqrt(periods_per_year), pstdev(downside)) if average_return is not None and len(downside) > 1 else None

    drawdowns = []
    peak = equities[0] if equities else float(initial_cash)
    current_duration = 0
    max_duration = 0
    for equity in equities:
        peak = max(peak, equity)
        drawdown = (peak - equity) / peak if peak else 0.0
        drawdowns.append(drawdown)
        current_duration = current_duration + 1 if drawdown > 0 else 0
        max_duration = max(max_duration, current_duration)
    max_drawdown = max(drawdowns, default=0.0)
    positive = [value for value in returns if value > 0]
    negative = [value for value in returns if value < 0]
    payoff = _safe_ratio(mean(positive), abs(mean(negative))) if positive and negative else None
    turnover = sum(float(fill.price * fill.quantity) for fill in result.fills) / float(initial_cash)
    holding = [
        result.fills[index].event_time_ns - result.fills[index - 1].event_time_ns
        for index in range(1, len(result.fills))
    ]
    tail_count = max(1, math.ceil(len(returns) * 0.05)) if returns else 0
    expected_shortfall = abs(mean(sorted(returns)[:tail_count])) if tail_count else None
    values: dict[str, float | None] = {
        "pnl": float(pnl),
        "total_return": total_return,
        "annualized_return": annualized,
        "volatility": volatility,
        "downside_volatility": downside_volatility,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": _safe_ratio(annualized, max_drawdown),
        "max_drawdown": max_drawdown,
        "average_drawdown": mean(drawdowns) if drawdowns else 0.0,
        "drawdown_duration": float(max_duration),
        "win_rate": len(positive) / len(returns) if returns else None,
        "payoff_ratio": payoff,
        "expectancy": average_return * float(initial_cash) if average_return is not None else None,
        "turnover": turnover,
        "average_holding_period": mean(holding) / 1_000_000_000 if holding else None,
        "expected_shortfall": expected_shortfall,
        "capacity_estimate": float(initial_cash) * 10,
    }
    values = {name: _stable_metric(value) for name, value in values.items()}
    reasons = {name: "insufficient observations for diagnostic metric" for name, value in values.items() if value is None}
    return values, reasons


def _annualization_policy(result: RunnerResult, asset_class: str) -> dict[str, Any]:
    timestamps = sorted({int(row["event_time_ns"]) for row in result.equity_curve})
    intervals = [
        current - previous
        for previous, current in zip(timestamps, timestamps[1:])
        if current > previous
    ]
    if not intervals:
        raise ValueError("annualized metrics require at least two distinct equity timestamps")
    interval_seconds = median(intervals) / 1_000_000_000
    if asset_class == "futures":
        calendar = "252_sessions_x_6.5_hours"
        periods_per_year = 252 * 6.5 * 60 * 60 / interval_seconds
    elif asset_class in {"crypto_spot", "prediction_market"}:
        calendar = "continuous_365.25_days"
        periods_per_year = 365.25 * 24 * 60 * 60 / interval_seconds
    else:
        raise ValueError(f"asset class requires an explicit annualization policy: {asset_class}")
    if not math.isfinite(periods_per_year) or periods_per_year <= 0:
        raise ValueError("annualization periods_per_year must be positive and finite")
    return {
        "method": "asset_calendar_over_median_equity_interval",
        "calendar": calendar,
        "median_interval_seconds": _stable_metric(interval_seconds),
        "periods_per_year": _stable_metric(periods_per_year),
    }


def _gross_equities(result: RunnerResult) -> list[float]:
    fill_costs = sorted(
        (
            fill.event_time_ns,
            fill.fee + fill.spread_cost + fill.slippage_cost,
        )
        for fill in result.fills
    )
    total_allocated = sum((cost for _timestamp, cost in fill_costs), Decimal(0))
    total_costs = sum(result.cost_components.values(), Decimal(0))
    if total_allocated != total_costs:
        raise ValueError("gross equity reconstruction requires every monetary cost to be timestamped")
    gross = []
    cumulative = Decimal(0)
    cursor = 0
    for row in result.equity_curve:
        timestamp = int(row["event_time_ns"])
        while cursor < len(fill_costs) and fill_costs[cursor][0] <= timestamp:
            cumulative += fill_costs[cursor][1]
            cursor += 1
        gross.append(float(Decimal(row["equity"]) + cumulative))
    return gross


def build_metrics_and_costs(
    result: RunnerResult,
    *,
    initial_cash: Decimal,
    created_at: str,
    start_time: str,
    end_time: str,
    asset_class: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    net_pnl = Decimal(result.final_snapshot["equity"]) - initial_cash
    costs = dict(result.cost_components)
    monetary_costs = sum(costs.values(), Decimal(0))
    gross_pnl = net_pnl + monetary_costs
    annualization = _annualization_policy(result, asset_class)
    periods_per_year = float(annualization["periods_per_year"])
    net_equities = [float(row["equity"]) for row in result.equity_curve]
    gross_equities = _gross_equities(result)
    net_metrics, net_reasons = _metrics(
        result,
        initial_cash,
        net_pnl,
        equities=net_equities,
        periods_per_year=periods_per_year,
    )
    gross_metrics, gross_reasons = _metrics(
        result,
        initial_cash,
        gross_pnl,
        equities=gross_equities,
        periods_per_year=periods_per_year,
    )
    reasons = {f"gross_metrics.{name}": reason for name, reason in gross_reasons.items()}
    reasons.update({f"net_metrics.{name}": reason for name, reason in net_reasons.items()})
    cost_waterfall = {
        "schema_version": 2,
        "id": f"{result.strategy_id}-costs",
        "run_receipt": "run_receipt.json",
        "created_at": created_at,
        "gross_pnl": float(gross_pnl),
        "costs": {name: float(value) for name, value in costs.items()},
        "net_pnl": float(net_pnl),
        "assumptions": {
            "fee_model": "explicit linear fee per fill",
            "fill_model": "subsequent evidence or next-bar open",
            "latency_model": "decision at receive time; no same-event fill",
            "depth_model": "available depth with conservative rejection",
        },
        "limitations": ["synthetic diagnostic data"],
    }
    metrics_report = {
        "schema_version": 2,
        "id": f"{result.strategy_id}-metrics",
        "run_receipt": "run_receipt.json",
        "created_at": created_at,
        "sample": {
            "start_time": start_time,
            "end_time": end_time,
            "evaluation_scope": "diagnostic",
            "trades": len(result.fills),
            "signals": result.signals,
            "instruments": sorted({intent.instrument_id for intent in result.intents}) or ["DIAGNOSTIC"],
        },
        "annualization": annualization,
        "gross_metrics": gross_metrics,
        "net_metrics": net_metrics,
        "not_applicable_reasons": reasons,
        "robustness": {
            "null_baseline_result": "not evaluated until V3",
            "dsr_or_psr": None,
            "pbo": None,
            "stress_results": [],
            "parameter_stability": "not evaluated until V3",
        },
        "limitations": ["diagnostic synthetic baseline; no promotion claim"],
    }
    return metrics_report, cost_waterfall


def render_markdown(strategy_id: str, metrics: dict[str, Any], costs: dict[str, Any]) -> str:
    net = metrics["net_metrics"]
    return (
        f"# {strategy_id}\n\n"
        "Status: diagnostic baseline\n\n"
        f"- Net PnL: {net['pnl']:.8f}\n"
        f"- Total return: {net['total_return']:.8f}\n"
        f"- Max drawdown: {net['max_drawdown']:.8f}\n"
        f"- Trades: {metrics['sample']['trades']}\n"
        f"- Fees: {costs['costs']['fees']:.8f}\n"
        f"- Slippage: {costs['costs']['slippage']:.8f}\n\n"
        "This report is read-only and does not grant promotion.\n"
    )


def render_html(strategy_id: str, metrics: dict[str, Any], costs: dict[str, Any]) -> str:
    rows = [
        ("Net PnL", metrics["net_metrics"]["pnl"]),
        ("Total return", metrics["net_metrics"]["total_return"]),
        ("Max drawdown", metrics["net_metrics"]["max_drawdown"]),
        ("Trades", metrics["sample"]["trades"]),
        ("Fees", costs["costs"]["fees"]),
        ("Slippage", costs["costs"]["slippage"]),
    ]
    body = "".join(f"<tr><th>{html.escape(label)}</th><td>{html.escape(str(value))}</td></tr>" for label, value in rows)
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<title>{html.escape(strategy_id)}</title>"
        "<style>body{font-family:system-ui,sans-serif;max-width:760px;margin:40px auto;padding:0 20px;color:#17202a}"
        "table{border-collapse:collapse;width:100%}th,td{padding:10px;border-bottom:1px solid #d5d8dc;text-align:left}"
        "small{color:#566573}</style></head><body>"
        f"<h1>{html.escape(strategy_id)}</h1><p>Diagnostic baseline</p><table>{body}</table>"
        "<p><small>Read-only evidence. No promotion or live capability.</small></p></body></html>"
    )

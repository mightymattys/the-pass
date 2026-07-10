"""Paper observation, divergence, and fail-closed incident artifacts."""

from __future__ import annotations

from typing import Any


def _ratio(observed: float, expected: float) -> float:
    return abs(observed - expected) / max(abs(expected), 1.0)


def build_paper_artifacts(
    *,
    source_package: str,
    strategy_spec: str,
    adapter: str,
    config_hash: str,
    instrument: str,
    paper_result: dict[str, Any],
    backtest_metrics: dict[str, Any],
    backtest_costs: dict[str, Any],
    start_time: str,
    end_time: str,
    observed_days: int,
    minimum_days: int,
    minimum_signals: int,
) -> dict[str, dict[str, Any]]:
    created_at = "2026-07-10T00:00:00Z"
    paper_plan = {
        "schema_version": 2,
        "id": "diagnostic-paper-plan-v1",
        "created_at": created_at,
        "source_package": source_package,
        "strategy_spec": strategy_spec,
        "adapter": adapter,
        "config_hash": config_hash,
        "observation": {
            "start_after": created_at,
            "minimum_days": minimum_days,
            "minimum_signals": minimum_signals,
            "instruments": [instrument],
        },
        "decision_logic": {"same_as_backtest": True, "differences": []},
        "divergence_policy": {
            "max_cost_divergence": "0.25",
            "max_signal_divergence": "0.05",
            "max_fill_divergence": "0.10",
            "stop_conditions": ["stale data", "outage", "clock skew", "risk breach"],
        },
        "safety": {
            "simulated_intents_only": True,
            "live_trading_enabled": False,
            "real_order_path_available": False,
            "credentials_required": False,
        },
        "status": "blocked",
    }
    observation = {
        "schema_version": 2,
        "id": "diagnostic-observation-v1",
        "created_at": created_at,
        "paper_plan": "paper_plan.json",
        "source_package": source_package,
        "data_capture": {
            "event_time_field": "event_time_ns",
            "receive_time_field": "receive_time_ns",
            "decision_time_field": "decision_time_ns",
            "storage_path": "paper_run.json",
        },
        "signals": {"format": "json", "fields": ["intent_id", "decision_time_ns", "side", "quantity"]},
        "simulated_orders": {
            "format": "json",
            "fields": ["intent_id", "side", "quantity", "price", "fee"],
            "cannot_reach_broker": True,
        },
        "quality": {
            "missing_data_policy": "freeze",
            "outage_policy": "freeze",
            "clock_skew_policy": "freeze",
        },
    }
    expected_signals = int(backtest_metrics["sample"]["signals"])
    expected_fills = int(backtest_metrics["sample"]["trades"])
    expected_cost = sum(float(value or 0) for value in backtest_costs["costs"].values())
    observed_signals = int(paper_result.get("signals", 0))
    observed_fills = len(paper_result.get("fills", []))
    observed_cost = sum(float(value or 0) for value in paper_result.get("cost_components", {}).values())
    observed_pnl = float(paper_result.get("final_snapshot", {}).get("equity", 100000)) - 100000
    expected_pnl = float(backtest_metrics["net_metrics"]["pnl"])
    comparisons = {
        "signal_divergence": _ratio(observed_signals, expected_signals),
        "cost_divergence": _ratio(observed_cost, expected_cost),
        "fill_divergence": _ratio(observed_fills, expected_fills),
        "pnl_divergence": _ratio(observed_pnl, expected_pnl),
        "latency_p95_ns": sorted(paper_result.get("latency_ns", [0]))[int(0.95 * max(len(paper_result.get("latency_ns", [0])) - 1, 0))],
    }
    breaches = []
    for field, threshold in (("signal_divergence", 0.05), ("cost_divergence", 0.25), ("fill_divergence", 0.10)):
        if comparisons[field] > threshold:
            breaches.append(
                {"threshold": f"{field} <= {threshold}", "observed": str(comparisons[field]), "blocks_promotion": True}
            )
    if observed_days < minimum_days or observed_signals < minimum_signals:
        breaches.append(
            {
                "threshold": f">= {minimum_days} days and >= {minimum_signals} signals",
                "observed": f"{observed_days} days and {observed_signals} signals",
                "blocks_promotion": True,
            }
        )
    divergence = {
        "schema_version": 2,
        "id": "diagnostic-divergence-v1",
        "created_at": created_at,
        "paper_plan": "paper_plan.json",
        "observation_manifest": "observation_manifest.json",
        "sample": {
            "start_time": start_time,
            "end_time": end_time,
            "signals": observed_signals,
            "simulated_orders": len(paper_result.get("simulated_intents", [])),
            "observed_days": observed_days,
        },
        "comparisons": comparisons,
        "breaches": breaches,
        "decision": {
            "status": "blocked" if breaches else "risk_review_candidate",
            "reason": "paper window or divergence gate is incomplete" if breaches else "all paper gates passed",
            "next_action": "continue observation without changing StrategySpec" if breaches else "independent risk review",
        },
    }
    return {"paper_plan": paper_plan, "observation_manifest": observation, "divergence_report": divergence}

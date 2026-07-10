#!/usr/bin/env python3
"""Build deterministic V3 robustness, risk, and independent audit evidence."""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from the_pass.audit import build_audit_report, reproduce_baseline_cli  # noqa: E402
from the_pass.data.contracts import canonical_value  # noqa: E402
from the_pass.engine.baselines import generate_synthetic_bars  # noqa: E402
from the_pass.risk import build_risk_policy_artifact, build_risk_report  # noqa: E402
from the_pass.robustness import (  # noqa: E402
    StressParameters,
    block_bootstrap_means,
    cscv_pbo,
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
    purged_walk_forward_splits,
    reality_check,
    regime_statistics,
    run_stress_suite,
    sensitivity_report,
)
from the_pass.validator import validate_artifact  # noqa: E402


def write_json(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(canonical_value(document, allow_float=True), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def return_matrix() -> tuple[list[list[float]], list[float], list[float], list[int]]:
    import numpy as np
    import pandas as pd

    events = generate_synthetic_bars(instrument_id="BTCUSDT", profile="trend")
    prices = pd.Series([float(event.payload["close"]) for event in events])
    returns = prices.pct_change().fillna(0.0)
    lookbacks = [5, 10, 20]
    columns = []
    for lookback in lookbacks:
        upper = prices.shift(1).rolling(lookback).max()
        lower = prices.shift(1).rolling(lookback).min()
        signal = pd.Series(np.where(prices > upper, 1.0, np.where(prices < lower, -1.0, np.nan))).ffill().fillna(0.0)
        turnover = signal.diff().abs().fillna(signal.abs())
        columns.append((signal.shift(1).fillna(0.0) * returns - turnover * 0.001).tolist())
    matrix = np.asarray(columns, dtype=float).T
    return matrix.tolist(), matrix[:, 1].tolist(), prices.tolist(), lookbacks


def split_summary(returns: list[float], *, anchored: bool) -> list[dict[str, Any]]:
    splits = purged_walk_forward_splits(
        len(returns), train_size=40, test_size=12, purge=2, embargo=2, anchored=anchored
    )
    return [
        {
            "train_start": split.train[0],
            "train_end": split.train[-1],
            "test_start": split.test[0],
            "test_end": split.test[-1],
            "purged": list(split.purged),
            "embargoed": list(split.embargoed),
            "train_mean": sum(returns[index] for index in split.train) / len(split.train),
            "test_mean": sum(returns[index] for index in split.test) / len(split.test),
        }
        for split in splits
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "reports" / "v3" / "donchian_momentum")
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    output = args.output.resolve()
    try:
        if args.clean and output.exists():
            shutil.rmtree(output)
        package = ROOT / "examples" / "b2-baselines" / "donchian_momentum" / "package"
        matrix, selected_returns, prices, lookbacks = return_matrix()
        trial_sharpes = []
        for variant in zip(*matrix):
            average = sum(variant) / len(variant)
            variance = sum((value - average) ** 2 for value in variant) / (len(variant) - 1)
            trial_sharpes.append(average / math.sqrt(variance) if variance else 0.0)
        pbo = cscv_pbo(matrix, blocks=8)
        psr = probabilistic_sharpe_ratio(selected_returns)
        dsr = deflated_sharpe_ratio(selected_returns, trial_sharpes=trial_sharpes)
        bootstrap = block_bootstrap_means(selected_returns, block_size=5, samples=500, seed=7)
        absolute_returns = sorted(abs(value) for value in selected_returns)
        median_abs = absolute_returns[len(absolute_returns) // 2]
        regimes = ["high_volatility" if abs(value) >= median_abs else "low_volatility" for value in selected_returns]
        screen = json.loads((package / "screen_results.json").read_text(encoding="utf-8"))
        sensitivity_rows = [
            {"lookback": row["parameters"]["lookback"], "net_return": row["net_return"]}
            for row in screen
        ]
        split = len(selected_returns) * 2 // 3
        in_sample = sum(selected_returns[:split])
        out_of_sample = sum(selected_returns[split:])
        robustness = {
            "schema_version": 1,
            "created_at": "2026-07-10T00:00:00Z",
            "target": "examples/b2-baselines/donchian_momentum/package",
            "variants": len(lookbacks),
            "lookbacks": lookbacks,
            "anchored_walk_forward": split_summary(selected_returns, anchored=True),
            "rolling_walk_forward": split_summary(selected_returns, anchored=False),
            "purge_observations": 2,
            "embargo_observations": 2,
            "pbo": pbo,
            "psr": psr,
            "dsr": dsr,
            "trial_sharpes": trial_sharpes,
            "bootstrap": {
                "seed": 7,
                "samples": 500,
                "mean": sum(bootstrap) / len(bootstrap),
                "p05": sorted(bootstrap)[24],
                "p95": sorted(bootstrap)[474],
            },
            "regimes": regime_statistics(selected_returns, regimes),
            "reality_check": reality_check(matrix, bootstrap_samples=500, seed=7),
            "sensitivity": sensitivity_report(
                sensitivity_rows,
                parameter="lookback",
                metric="net_return",
                selected_value=10,
            ),
            "is_oos_degradation": {
                "in_sample_return": in_sample,
                "out_of_sample_return": out_of_sample,
                "degradation": in_sample - out_of_sample,
            },
            "finite_probability_checks": {
                "pbo": 0 <= pbo["pbo"] <= 1,
                "psr": 0 <= psr <= 1,
                "dsr": 0 <= dsr <= 1,
            },
        }

        costs = json.loads((package / "cost_waterfall.json").read_text(encoding="utf-8"))
        stress = run_stress_suite(
            StressParameters(
                gross_pnl=Decimal(str(costs["gross_pnl"])),
                fees=Decimal(str(costs["costs"]["fees"])),
                slippage=Decimal(str(costs["costs"]["slippage"])),
                missed_fill_cost=Decimal(2),
                outage_loss=Decimal(10),
                gap_loss=Decimal(30),
                deleverage_loss=Decimal(40),
            )
        )
        policy = build_risk_policy_artifact("crypto_intraday")
        ledger_entry = json.loads((package / "receipt-ledger.jsonl").read_text(encoding="utf-8").splitlines()[0])
        blockers = [
            "synthetic sample does not provide 12 to 24 months of history",
            "two fills are below the 500-trade intraday threshold",
            "next-bar synthetic fills are not executable book replay",
        ]
        if pbo["pbo"] > policy["promotion_thresholds"]["maximum_pbo"]:
            blockers.append("PBO exceeds the crypto intraday threshold")
        if any(not result["pass"] for result in stress):
            blockers.append("one or more mandatory stress scenarios is net-negative")
        risk_report = build_risk_report(
            package_id=ledger_entry["package_id"],
            policy=policy,
            returns=selected_returns,
            scenario_losses=stress,
            capacity=1_000_000,
            blockers=blockers,
        )
        reproduction = reproduce_baseline_cli("donchian_momentum", package)
        stats_findings = [
            {
                "severity": "P2",
                "title": "History and trade-count gates are not met",
                "evidence": "risk_report.json",
                "status": "confirmed",
                "recommendation": "Collect the required history and at least 500 intraday trades before promotion review.",
                "promotion_impact": "blocks_promotion",
                "blocks_promotion": True,
            }
        ]
        if pbo["pbo"] > policy["promotion_thresholds"]["maximum_pbo"]:
            stats_findings.append(
                {
                    "severity": "P2",
                    "title": "PBO exceeds the asset policy threshold",
                    "evidence": "robustness_report.json",
                    "status": "confirmed",
                    "recommendation": "Reduce the strategy zoo or add independent history before retesting.",
                    "promotion_impact": "blocks_promotion",
                    "blocks_promotion": True,
                }
            )
        stats_audit = build_audit_report(
            report_id="donchian-stats-audit-v1",
            target="examples/b2-baselines/donchian_momentum/package",
            owner="strategy_implementer",
            reviewer="stats_auditor",
            findings=stats_findings,
            evidence=["robustness_report.json", "risk_report.json", "reproduction_report.json"],
            limitations=["synthetic fixture cannot establish market edge"],
        )
        execution_audit = build_audit_report(
            report_id="donchian-execution-audit-v1",
            target="examples/b2-baselines/donchian_momentum/package",
            owner="strategy_implementer",
            reviewer="execution_skeptic",
            findings=[
                {
                    "severity": "P2",
                    "title": "Bar fills do not prove executable liquidity",
                    "evidence": "../../../examples/b2-baselines/donchian_momentum/package/run_receipt.json",
                    "status": "confirmed",
                    "recommendation": "Repeat on archived trades and books with depth, latency, and rejection evidence.",
                    "promotion_impact": "blocks_promotion",
                    "blocks_promotion": True,
                }
            ],
            evidence=["stress_report.json", "reproduction_report.json"],
            limitations=["no venue archive or order-book replay"],
        )

        artifacts = {
            "robustness_report.json": robustness,
            "stress_report.json": {"schema_version": 1, "created_at": "2026-07-10T00:00:00Z", "scenarios": stress},
            "risk_policy.json": policy,
            "risk_report.json": risk_report,
            "stats_audit.json": stats_audit,
            "execution_audit.json": execution_audit,
            "reproduction_report.json": reproduction,
        }
        for name, document in artifacts.items():
            write_json(output / name, document)
        for name, artifact_type in (
            ("risk_policy.json", "risk_policy"),
            ("risk_report.json", "risk_report"),
            ("stats_audit.json", "audit_report"),
            ("execution_audit.json", "audit_report"),
        ):
            validation = validate_artifact(output / name, artifact_type=artifact_type)
            if not validation.ok:
                details = "; ".join(f"{issue.path}: {issue.message}" for issue in validation.issues)
                raise RuntimeError(f"generated {name} failed validation: {details}")
        response = {"ok": True, "status": "complete", "artifact_paths": [str(output / name) for name in artifacts], "issues": [], "receipt_id": None}
        print(json.dumps(response, indent=2, sort_keys=True) if args.format == "json" else "V3 audit evidence generated")
        return 0
    except Exception as exc:
        response = {"ok": False, "status": "error", "artifact_paths": [], "issues": [{"path": str(output), "message": str(exc)}], "receipt_id": None}
        print(json.dumps(response) if args.format == "json" else f"V3 audit failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

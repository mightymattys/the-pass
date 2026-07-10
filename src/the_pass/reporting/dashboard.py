"""Static HTML dashboard generated from artifacts and DuckDB aggregation."""

from __future__ import annotations

import html
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

import yaml


DASHBOARD_VIEWS = (
    "research_backlog",
    "strategy_status",
    "experiments",
    "robustness",
    "cost_waterfall",
    "risk",
    "paper_divergence",
    "incidents",
    "receipt_ledger",
)


STYLE = """
body{font-family:system-ui,sans-serif;margin:0;color:#182026;background:#f7f8f8}
header{background:#182026;color:#fff;padding:18px 24px}header h1{margin:0;font-size:22px;letter-spacing:0}
nav{display:flex;gap:8px;flex-wrap:wrap;padding:12px 24px;background:#fff;border-bottom:1px solid #d9dddf}
nav a{color:#1f4f5f;text-decoration:none;padding:6px 8px}main{max-width:1120px;margin:0 auto;padding:24px}
table{width:100%;border-collapse:collapse;background:#fff}th,td{text-align:left;padding:9px;border-bottom:1px solid #e2e5e7}
th{background:#eef1f2}code{font-size:12px}.blocked{color:#a33b20}.pass{color:#177245}
"""


def _page(title: str, body: str) -> str:
    navigation = "".join(f'<a href="{view}.html">{html.escape(view.replace("_", " ").title())}</a>' for view in DASHBOARD_VIEWS)
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"><title>{html.escape(title)}</title>"
        f"<style>{STYLE}</style></head><body><header><h1>The Pass: {html.escape(title)}</h1></header>"
        f"<nav>{navigation}</nav><main>{body}</main></body></html>"
    )


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    head = "".join(f"<th>{html.escape(header)}</th>" for header in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(value))}</td>" for value in row) + "</tr>" for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _experiment_rows(repo_root: Path) -> list[dict[str, Any]]:
    rows = []
    for package in sorted((repo_root / "examples" / "b2-baselines").glob("*/package")):
        metrics = json.loads((package / "metrics_report.json").read_text(encoding="utf-8"))
        verdict = json.loads((package / "verdict_report.json").read_text(encoding="utf-8"))
        rows.append(
            {
                "name": package.parent.name,
                "strategy_id": metrics["id"].removesuffix("-metrics"),
                "pnl": float(metrics["net_metrics"]["pnl"]),
                "trades": int(metrics["sample"]["trades"]),
                "verdict": verdict["verdict"],
            }
        )
    return rows


def _duckdb_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    try:
        import duckdb
    except ImportError as exc:
        raise RuntimeError("static dashboard requires the 'data' extra") from exc
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("CREATE TABLE experiments(name VARCHAR, pnl DOUBLE, trades INTEGER, verdict VARCHAR)")
        connection.executemany(
            "INSERT INTO experiments VALUES (?, ?, ?, ?)",
            [(row["name"], row["pnl"], row["trades"], row["verdict"]) for row in rows],
        )
        count, total_pnl, total_trades = connection.execute(
            "SELECT COUNT(*), SUM(pnl), SUM(trades) FROM experiments"
        ).fetchone()
        return {"experiments": count, "diagnostic_total_pnl": total_pnl, "fills": total_trades}
    finally:
        connection.close()


def build_static_dashboard(repo_root: Path, output_dir: Path) -> list[Path]:
    repo_root = repo_root.resolve()
    output_dir = output_dir.resolve()
    experiments = _experiment_rows(repo_root)
    summary = _duckdb_summary(experiments)
    sources = yaml.safe_load((repo_root / "research" / "sources.yaml").read_text(encoding="utf-8"))
    risk = json.loads((repo_root / "reports" / "v3" / "donchian_momentum" / "risk_report.json").read_text(encoding="utf-8"))
    robustness = json.loads(
        (repo_root / "reports" / "v3" / "donchian_momentum" / "robustness_report.json").read_text(encoding="utf-8")
    )
    divergence_path = repo_root / "reports" / "p4" / "synthetic_observation" / "divergence_report.json"
    divergence = json.loads(divergence_path.read_text(encoding="utf-8")) if divergence_path.is_file() else None
    incidents = [json.loads(path.read_text(encoding="utf-8")) for path in sorted((repo_root / "reports").glob("**/incident*.json"))]

    source_rows = sources.get("sources", sources if isinstance(sources, list) else [])
    pages = {
        "research_backlog": _table(
            ["Source", "Category", "Status"],
            [[row.get("id"), row.get("category"), row.get("status")] for row in source_rows],
        ),
        "strategy_status": _table(
            ["Strategy", "Verdict", "Net PnL", "Fills"],
            [[row["strategy_id"], row["verdict"], row["pnl"], row["trades"]] for row in experiments],
        ),
        "experiments": (
            f"<p>DuckDB aggregation: {summary['experiments']} experiments, {summary['fills']} fills, "
            f"diagnostic total PnL {summary['diagnostic_total_pnl']}.</p>"
            + _table(["Run", "Strategy", "Net PnL", "Verdict"], [[row["name"], row["strategy_id"], row["pnl"], row["verdict"]] for row in experiments])
        ),
        "robustness": _table(
            ["Metric", "Value"],
            [["PBO", robustness["pbo"]["pbo"]], ["PSR", robustness["psr"]], ["DSR", robustness["dsr"]]],
        ),
        "cost_waterfall": _table(
            ["Run", "Gross", "Fees", "Slippage", "Net"],
            [
                [
                    row["name"],
                    (cost := json.loads((repo_root / "examples" / "b2-baselines" / row["name"] / "package" / "cost_waterfall.json").read_text(encoding="utf-8")))["gross_pnl"],
                    cost["costs"]["fees"],
                    cost["costs"]["slippage"],
                    cost["net_pnl"],
                ]
                for row in experiments
            ],
        ),
        "risk": _table(
            ["Field", "Value"],
            [["Verdict", risk["verdict"]], ["Expected shortfall", risk["expected_shortfall"]], ["Risk-of-ruin proxy", risk["risk_of_ruin_proxy"]], ["Policy hash", risk["policy_hash"]]],
        ),
        "paper_divergence": (
            _table(
                ["Metric", "Value"],
                [[key, value] for key, value in divergence["comparisons"].items()] + [["Decision", divergence["decision"]["status"]]],
            )
            if divergence
            else "<p class=\"blocked\">No paper observation artifact exists.</p>"
        ),
        "incidents": _table(
            ["ID", "Severity", "Status", "Summary"],
            [[item["id"], item["severity"], item["status"], item["summary"]] for item in incidents],
        ) if incidents else "<p>No incidents recorded.</p>",
        "receipt_ledger": _table(
            ["Run", "Package ID", "Entry hash"],
            [
                [
                    package.parent.name,
                    (entry := json.loads((package / "receipt-ledger.jsonl").read_text(encoding="utf-8").splitlines()[0]))["package_id"],
                    entry["entry_hash"],
                ]
                for package in sorted((repo_root / "examples" / "b2-baselines").glob("*/package"))
            ],
        ),
    }
    staging = Path(tempfile.mkdtemp(prefix="the-pass-dashboard-", dir=str(output_dir.parent)))
    try:
        written = []
        for view in DASHBOARD_VIEWS:
            path = staging / f"{view}.html"
            path.write_text(_page(view.replace("_", " ").title(), pages[view]), encoding="utf-8")
            written.append(path)
        index = staging / "index.html"
        index.write_text(
            _page(
                "Evidence Dashboard",
                f"<p>{summary['experiments']} diagnostic experiments. All views are read-only.</p>"
                + _table(["View"], [[view.replace("_", " ").title()] for view in DASHBOARD_VIEWS]),
            ),
            encoding="utf-8",
        )
        written.append(index)
        if output_dir.exists():
            shutil.rmtree(output_dir)
        staging.rename(output_dir)
        return [output_dir / path.name for path in written]
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

"""Package-level paper-candidate promotion rules."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from ..candidate_contract import candidate_assembly_manifest
from .common import is_finite_number, normalize_identity, parse_timestamp, require_ordered_interval
from .models import ValidationIssue
from .registry import PACKAGE_CORE_ARTIFACTS


def validate_paper_candidate(
    *,
    promotion_documents: dict[str, dict[str, Any]],
    issues: list[ValidationIssue],
    receipt: dict[str, Any],
    strategy_spec: dict[str, Any],
    metrics: dict[str, Any],
    verdict: dict[str, Any],
    documents: dict[str, dict[str, Any]],
    promotion_evidence: list[tuple[str, Path]],
    linked_source_note_documents: list[dict[str, Any]],
    adapter: dict[str, Any] | None,
    costs: dict[str, Any],
    sample: dict[str, Any],
    sample_interval: tuple[Any, Any] | None,
    data_manifest: dict[str, Any],
) -> None:
    robustness_report = promotion_documents.get("robustness_report")
    if robustness_report is None:
        issues.append(
            ValidationIssue(
                "$.robustness_report",
                "paper_candidate requires a validated robustness_report.v3 artifact",
            )
        )
    else:
        if robustness_report.get("schema_version") != 3:
            issues.append(
                ValidationIssue(
                    "$.robustness_report.schema_version",
                    "new paper_candidate packages require robustness_report.v3",
                )
            )
        source_package_id = receipt.get("supersedes_package_id")
        if (
            source_package_id is not None
            and robustness_report.get("source_package_id") != source_package_id
        ):
            issues.append(
                ValidationIssue(
                    "$.robustness_report.source_package_id",
                    "must match run_receipt.supersedes_package_id",
                )
            )
        expected_assembly = candidate_assembly_manifest(
            strategy=strategy_spec,
            metrics=metrics,
            verdict=verdict,
            robustness=robustness_report,
            findings=documents.get("findings", {}),
        )
        if receipt.get("candidate_assembly") != expected_assembly:
            issues.append(
                ValidationIssue(
                    "$.run_receipt.candidate_assembly",
                    "must match the deterministic candidate assembly contract",
                )
            )
        if robustness_report.get("promotion_eligible") is not True:
            issues.append(
                ValidationIssue(
                    "$.robustness_report.promotion_eligible",
                    "paper_candidate requires promotion-eligible robustness evidence",
                )
            )
        robustness_evidence = verdict.get("evidence", {}).get(
            "robustness_report"
        )
        robustness_path = next(
            (
                path
                for artifact_type, path in promotion_evidence
                if artifact_type == "robustness_report"
            ),
            None,
        )
        if (
            robustness_path is None
            or robustness_evidence != robustness_path.name
        ):
            issues.append(
                ValidationIssue(
                    "$.verdict_report.evidence.robustness_report",
                    "must reference the exact robustness_report artifact",
                )
            )
    non_v2 = sorted(
        artifact_type
        for artifact_type in PACKAGE_CORE_ARTIFACTS
        if documents[artifact_type].get("schema_version") != 2
    )
    if non_v2:
        issues.append(
            ValidationIssue(
                "$.schema_version",
                "paper_candidate requires v2 core artifacts: " + ", ".join(non_v2),
            )
        )
    if strategy_spec.get("status") not in {"research", "paper_candidate"}:
        issues.append(
            ValidationIssue(
                "$.strategy_spec.status",
                "paper_candidate requires a research-ready StrategySpec",
            )
        )
    if not linked_source_note_documents:
        issues.append(
            ValidationIssue(
                "$.verdict_report.evidence.source_notes",
                "paper_candidate requires source notes",
            )
        )
    for index, source_note in enumerate(linked_source_note_documents):
        if source_note.get("status") not in {"reviewed", "implemented"}:
            issues.append(
                ValidationIssue(
                    f"$.verdict_report.evidence.source_notes[{index}]",
                    "paper_candidate requires reviewed or implemented source notes",
                )
            )
    findings = documents.get("findings")
    if findings is None:
        issues.append(
            ValidationIssue(
                "$.findings",
                "paper_candidate requires independent findings with a passed research_gate",
            )
        )
    else:
        summary = findings["summary"]
        if findings["target_gate"] != "research_gate":
            issues.append(
                ValidationIssue(
                    "$.findings.target_gate",
                    "must be research_gate for paper_candidate",
                )
            )
        if summary["gate_result"] != "pass":
            issues.append(
                ValidationIssue(
                    "$.findings.summary.gate_result",
                    "must be pass for paper_candidate",
                )
            )
        reviewer = findings["reviewer"]
        normalized_reviewer = normalize_identity(reviewer)
        owners = {
            normalize_identity(owner)
            for owner in (strategy_spec.get("owner"), receipt.get("owner"))
            if normalize_identity(owner)
        }
        if normalized_reviewer in owners:
            issues.append(
                ValidationIssue(
                    "$.findings.reviewer",
                    "must be independent from strategy and run owners",
                )
            )
        if normalize_identity(verdict.get("owner")) != normalized_reviewer:
            issues.append(
                ValidationIssue(
                    "$.verdict_report.owner",
                    "must match the independent findings reviewer",
                )
            )

    failed_gates = verdict.get("gate_results", {}).get("failed_gates", [])
    if failed_gates:
        issues.append(
            ValidationIssue(
                "$.verdict_report.gate_results.failed_gates",
                "must be empty for paper_candidate",
            )
        )
    if adapter is None or adapter.get("mode") not in {"research", "paper"}:
        issues.append(
            ValidationIssue(
                "$.adapter.mode",
                "paper_candidate requires a research or paper adapter",
            )
        )
    if not is_finite_number(costs.get("gross_pnl")) or not is_finite_number(
        costs.get("net_pnl")
    ):
        issues.append(
            ValidationIssue(
                "$.cost_waterfall",
                "paper_candidate requires numeric gross_pnl and net_pnl",
            )
        )
    cost_components = costs.get("costs", {})
    required_costs = ("fees", "spread", "slippage", "impact")
    if not isinstance(cost_components, dict) or any(
        not is_finite_number(cost_components.get(field))
        or cost_components[field] < 0
        for field in required_costs
    ):
        issues.append(
            ValidationIssue(
                "$.cost_waterfall.costs",
                "paper_candidate requires non-negative numeric fees, spread, slippage, and impact",
            )
        )
    elif is_finite_number(costs.get("gross_pnl")) and is_finite_number(
        costs.get("net_pnl")
    ):
        numeric_costs = [
            value for value in cost_components.values() if is_finite_number(value)
        ]
        expected_net = costs["gross_pnl"] - sum(numeric_costs)
        if not math.isclose(
            costs["net_pnl"], expected_net, rel_tol=1e-9, abs_tol=1e-12
        ):
            issues.append(
                ValidationIssue(
                    "$.cost_waterfall.net_pnl",
                    "must equal gross_pnl minus numeric cost components",
                )
            )
    cost_assumptions = costs.get("assumptions", {})
    required_assumptions = (
        "fee_model",
        "fill_model",
        "latency_model",
        "depth_model",
    )
    if not isinstance(cost_assumptions, dict) or any(
        not isinstance(cost_assumptions.get(field), str)
        or not cost_assumptions[field].strip()
        or cost_assumptions[field].strip().lower()
        in {"none", "n/a", "not applicable"}
        for field in required_assumptions
    ):
        issues.append(
            ValidationIssue(
                "$.cost_waterfall.assumptions",
                "paper_candidate requires explicit fee, fill, latency, and depth assumptions",
            )
        )
    required_promotion_metrics = (
        "pnl",
        "total_return",
        "sharpe",
        "max_drawdown",
        "turnover",
        "expectancy",
    )
    annualization = metrics.get("annualization")
    if (
        not isinstance(annualization, dict)
        or not is_finite_number(annualization.get("periods_per_year"))
        or annualization["periods_per_year"] <= 0
        or not isinstance(annualization.get("method"), str)
        or not annualization["method"].strip()
    ):
        issues.append(
            ValidationIssue(
                "$.metrics_report.annualization",
                "paper_candidate requires an explicit positive annualization policy",
            )
        )
    for metric_group in ("gross_metrics", "net_metrics"):
        values = metrics.get(metric_group, {})
        missing_metrics = [
            metric_name
            for metric_name in required_promotion_metrics
            if not isinstance(values, dict)
            or not is_finite_number(values.get(metric_name))
        ]
        if missing_metrics:
            issues.append(
                ValidationIssue(
                    f"$.metrics_report.{metric_group}",
                    "paper_candidate requires numeric "
                    + ", ".join(missing_metrics),
                )
            )
    robustness = metrics.get("robustness", {})
    baseline_result = (
        robustness.get("null_baseline_result")
        if isinstance(robustness, dict)
        else None
    )
    if not isinstance(baseline_result, str) or not baseline_result.strip():
        issues.append(
            ValidationIssue(
                "$.metrics_report.robustness.null_baseline_result",
                "paper_candidate verdicts require a recorded null/random baseline result",
            )
        )
    elif (
        baseline_result.strip()
        .lower()
        .startswith(("not applicable", "n/a", "none"))
    ):
        issues.append(
            ValidationIssue(
                "$.metrics_report.robustness.null_baseline_result",
                "paper_candidate requires a null or random baseline result",
            )
        )
    trades = sample.get("trades") if isinstance(sample, dict) else None
    if not isinstance(trades, int) or isinstance(trades, bool) or trades < 1:
        issues.append(
            ValidationIssue(
                "$.metrics_report.sample.trades",
                "paper_candidate requires at least one trade",
            )
        )
    if (
        not isinstance(sample, dict)
        or sample.get("evaluation_scope") not in {"out_of_sample", "walk_forward"}
        or not sample.get("holdout_start_time")
        or not sample.get("holdout_end_time")
    ):
        issues.append(
            ValidationIssue(
                "$.metrics_report.sample",
                "paper_candidate requires an explicit out-of-sample or walk-forward holdout window",
            )
        )
    else:
        holdout_interval = require_ordered_interval(
            sample.get("holdout_start_time"),
            sample.get("holdout_end_time"),
            "$.metrics_report.sample.holdout",
            issues,
        )
        if (
            sample_interval
            and holdout_interval
            and (
                holdout_interval[0] < sample_interval[0]
                or holdout_interval[1] > sample_interval[1]
            )
        ):
            issues.append(
                ValidationIssue(
                    "$.metrics_report.sample.holdout",
                    "holdout window must be contained by the sample window",
                )
            )
    if not isinstance(robustness, dict) or not any(
        is_finite_number(robustness.get(field)) for field in ("dsr_or_psr", "pbo")
    ):
        issues.append(
            ValidationIssue(
                "$.metrics_report.robustness",
                "paper_candidate requires numeric DSR/PSR or PBO evidence",
            )
        )
    if not isinstance(robustness, dict) or not robustness.get("stress_results"):
        issues.append(
            ValidationIssue(
                "$.metrics_report.robustness.stress_results",
                "paper_candidate requires stress-test results",
            )
        )
    parameter_stability = (
        robustness.get("parameter_stability")
        if isinstance(robustness, dict)
        else None
    )
    if (
        not isinstance(parameter_stability, str)
        or not parameter_stability.strip()
        or parameter_stability.strip()
        .lower()
        .startswith(("not applicable", "n/a", "none"))
    ):
        issues.append(
            ValidationIssue(
                "$.metrics_report.robustness.parameter_stability",
                "paper_candidate requires parameter-stability evidence",
            )
        )
    if robustness_report is not None and isinstance(robustness, dict):
        expected_robustness = {
            "null_baseline_result": robustness_report["null_baseline"][
                "summary"
            ],
            "dsr_or_psr": robustness_report["statistics"]["dsr"],
            "pbo": robustness_report["statistics"]["pbo"]["pbo"],
            "stress_results": [
                row["summary"] for row in robustness_report["stress_results"]
            ],
            "parameter_stability": robustness_report[
                "parameter_stability"
            ]["summary"],
        }
        for field, expected in expected_robustness.items():
            observed = robustness.get(field)
            if isinstance(expected, float):
                matches = is_finite_number(observed) and math.isclose(
                    observed, expected, rel_tol=1e-12, abs_tol=1e-15
                )
            else:
                matches = observed == expected
            if not matches:
                issues.append(
                    ValidationIssue(
                        f"$.metrics_report.robustness.{field}",
                        "must be derived from the exact robustness_report",
                    )
                )
        validation_evidence = robustness_report["validation"]
        if (
            sample.get("evaluation_scope") != "walk_forward"
            or sample.get("holdout_start_time")
            != validation_evidence["holdout_start_time"]
            or sample.get("holdout_end_time")
            != validation_evidence["holdout_end_time"]
        ):
            issues.append(
                ValidationIssue(
                    "$.metrics_report.sample",
                    "walk-forward scope and holdout must match robustness_report",
                )
            )
    execution = strategy_spec.get("execution", {})
    required_execution = (
        "order_type",
        "fill_model",
        "latency_assumption_ms",
        "fee_model",
        "slippage_model",
    )
    if (
        not isinstance(execution, dict)
        or any(
            field not in execution or execution[field] in (None, "")
            for field in required_execution
        )
        or execution.get("order_type") == "diagnostic_only"
        or any(
            isinstance(execution.get(field), str)
            and execution[field].strip().lower()
            in {"none", "n/a", "not applicable"}
            for field in ("fill_model", "fee_model", "slippage_model")
        )
    ):
        issues.append(
            ValidationIssue(
                "$.strategy_spec.execution",
                "paper_candidate requires explicit order, fill, latency, fee, and slippage assumptions",
            )
        )
    validation_plan = strategy_spec.get("validation", {})
    if not isinstance(validation_plan, dict) or any(
        not isinstance(validation_plan.get(field), str)
        or not validation_plan[field].strip()
        or validation_plan[field]
        .strip()
        .lower()
        .startswith(("not applicable", "n/a", "none"))
        for field in ("train_test_split", "holdout_policy")
    ):
        issues.append(
            ValidationIssue(
                "$.strategy_spec.validation",
                "paper_candidate requires explicit train/test split and holdout policy",
            )
        )
    windows = (
        validation_plan.get("windows")
        if isinstance(validation_plan, dict)
        else None
    )
    if not isinstance(windows, dict):
        issues.append(
            ValidationIssue(
                "$.strategy_spec.validation.windows",
                "paper_candidate requires explicit train, validation, and holdout windows",
            )
        )
    else:
        train = require_ordered_interval(
            windows.get("train_start"),
            windows.get("train_end"),
            "$.strategy_spec.validation.windows.train",
            issues,
        )
        validation = require_ordered_interval(
            windows.get("validation_start"),
            windows.get("validation_end"),
            "$.strategy_spec.validation.windows.validation",
            issues,
        )
        holdout = require_ordered_interval(
            windows.get("holdout_start"),
            windows.get("holdout_end"),
            "$.strategy_spec.validation.windows.holdout",
            issues,
        )
        if (
            train
            and validation
            and holdout
            and not (train[1] <= validation[0] and validation[1] <= holdout[0])
        ):
            issues.append(
                ValidationIssue(
                    "$.strategy_spec.validation.windows",
                    "train, validation, and holdout windows must be ordered and non-overlapping",
                )
            )
        if holdout and (
            holdout[0] != parse_timestamp(sample.get("holdout_start_time"))
            or holdout[1] != parse_timestamp(sample.get("holdout_end_time"))
        ):
            issues.append(
                ValidationIssue(
                    "$.strategy_spec.validation.windows.holdout",
                    "must match the metrics holdout window",
                )
            )
    fingerprint = data_manifest.get("fingerprint", {})
    if fingerprint.get("method") != "sha256" or not isinstance(
        fingerprint.get("value"), str
    ):
        issues.append(
            ValidationIssue(
                "$.data_manifest.fingerprint",
                "paper_candidate requires a SHA-256 fingerprint",
            )
        )

    for metric_field, cost_field in (("pnl", "gross_pnl"),):
        if (
            is_finite_number(metrics.get("gross_metrics", {}).get(metric_field))
            and is_finite_number(costs.get(cost_field))
            and not math.isclose(
                metrics["gross_metrics"][metric_field],
                costs.get(cost_field),
                rel_tol=1e-9,
                abs_tol=1e-12,
            )
        ):
            issues.append(
                ValidationIssue(
                    "$.metrics_report.gross_metrics.pnl",
                    "must equal cost_waterfall.gross_pnl",
                )
            )
    if (
        is_finite_number(metrics.get("net_metrics", {}).get("pnl"))
        and is_finite_number(costs.get("net_pnl"))
        and not math.isclose(
            metrics["net_metrics"]["pnl"],
            costs.get("net_pnl"),
            rel_tol=1e-9,
            abs_tol=1e-12,
        )
    ):
        issues.append(
            ValidationIssue(
                "$.metrics_report.net_metrics.pnl",
                "must equal cost_waterfall.net_pnl",
            )
        )

"""Per-artifact workflow invariants."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from .common import is_finite_number, require_ordered_interval
from .models import ValidationIssue
from .robustness import validate_robustness_report_v3

def validate_workflow_artifact(
    artifact_type: str,
    document: dict[str, Any],
    *,
    ledger_path: Path | None = None,
    artifact_path: Path | None = None,
) -> list[ValidationIssue]:
    """Check workflow invariants that are awkward or unclear in JSON Schema."""

    issues: list[ValidationIssue] = []

    if artifact_type == "robustness_report" and document.get("schema_version") == 3:
        return validate_robustness_report_v3(
            document,
            ledger_path=ledger_path,
            artifact_path=artifact_path,
        )

    if artifact_type == "run_receipt":
        lineage_fields = (
            "supersedes_package_id",
            "supersedes_artifacts_hash",
        )
        if sum(field in document for field in lineage_fields) == 1:
            issues.append(
                ValidationIssue(
                    "$",
                    "successor run receipt requires both supersedes lineage fields",
                )
            )

    if artifact_type == "metrics_report" and document.get("schema_version") == 2:
        reasons = document["not_applicable_reasons"]
        for group_name in ("gross_metrics", "net_metrics"):
            for metric_name, value in document[group_name].items():
                reason_key = f"{group_name}.{metric_name}"
                if value is None and not reasons.get(reason_key):
                    issues.append(
                        ValidationIssue(
                            f"$.not_applicable_reasons.{reason_key}",
                            "must explain every null v2 metric",
                        )
                    )
                if value is not None and not is_finite_number(value):
                    issues.append(
                        ValidationIssue(
                            f"$.{group_name}.{metric_name}",
                            "must be a finite number or null",
                        )
                    )

    if artifact_type == "robustness_report":
        from ..robustness import (
            cscv_pbo,
            deflated_sharpe_ratio,
            probabilistic_sharpe_ratio,
            reality_check,
        )
        from ..data.contracts import stable_fingerprint

        registration = document["registration"]
        registration_fingerprint = registration.get("registration_fingerprint")
        registration_core = {
            key: value
            for key, value in registration.items()
            if key != "registration_fingerprint"
        }
        if registration_fingerprint != stable_fingerprint(registration_core):
            issues.append(
                ValidationIssue(
                    "$.registration.registration_fingerprint",
                    "does not match the registered experiment inputs",
                )
            )

        expected_report_fingerprint = stable_fingerprint(
            {
                key: value
                for key, value in document.items()
                if key != "report_fingerprint"
            }
        )
        if document["report_fingerprint"] != expected_report_fingerprint:
            issues.append(
                ValidationIssue(
                    "$.report_fingerprint",
                    "does not match the robustness report contents",
                )
            )

        matrix = document["matrix"]
        variants = registration["variants"]
        selected_index = registration["selected_index"]
        folds = document["validation"]["folds"]
        cells = document["cells"]
        if selected_index >= len(variants):
            issues.append(
                ValidationIssue(
                    "$.registration.selected_index",
                    "must identify a registered variant",
                )
            )
        null_index = document["null_baseline"]["variant_index"]
        if null_index >= len(variants) or null_index == selected_index:
            issues.append(
                ValidationIssue(
                    "$.null_baseline.variant_index",
                    "must identify a registered variant distinct from the selected variant",
                )
            )
        if len(matrix) != len(folds):
            issues.append(
                ValidationIssue("$.matrix", "must contain one row per validation fold")
            )
        if any(len(row) != len(variants) for row in matrix):
            issues.append(
                ValidationIssue("$.matrix", "must contain one column per registered variant")
            )
        expected_cells = len(matrix) * len(variants)
        if len(cells) != expected_cells:
            issues.append(
                ValidationIssue(
                    "$.cells", "must contain exactly one cell per fold and variant"
                )
            )
        observed_keys: set[tuple[int, int]] = set()
        for index, cell in enumerate(cells):
            if not isinstance(cell, dict):
                continue
            key = (cell["fold_id"], cell["variant_index"])
            if key in observed_keys:
                issues.append(
                    ValidationIssue(
                        f"$.cells[{index}]",
                        "duplicates a fold and variant cell",
                    )
                )
                continue
            observed_keys.add(key)
            fold_id, variant_index = key
            if not (
                0 <= fold_id < len(matrix)
                and 0 <= variant_index < len(variants)
            ):
                issues.append(
                    ValidationIssue(
                        f"$.cells[{index}]",
                        "fold_id or variant_index is outside the registered matrix",
                    )
                )
                continue
            matrix_value = matrix[fold_id][variant_index]
            cell_value = cell["net_return"]
            if matrix_value is None:
                matches = cell["status"] == "failed" and cell_value is None
            else:
                matches = (
                    cell["status"] == "complete"
                    and is_finite_number(cell_value)
                    and math.isclose(
                        cell_value,
                        matrix_value,
                        rel_tol=1e-12,
                        abs_tol=1e-15,
                    )
                )
            if not matches:
                issues.append(
                    ValidationIssue(
                        f"$.cells[{index}]",
                        "must match the status and return in the registered matrix",
                    )
                )
        if document["validation"]["mode"] == "purged_walk_forward":
            for index, fold in enumerate(folds):
                if fold["id"] != index:
                    issues.append(
                        ValidationIssue(
                            f"$.validation.folds[{index}].id",
                            "fold IDs must be contiguous and match matrix row order",
                        )
                    )
                if not (
                    fold["train_start"] < fold["train_end"] <= fold["test_start"]
                    < fold["test_end"]
                ):
                    issues.append(
                        ValidationIssue(
                            f"$.validation.folds[{index}]",
                            "train and test intervals must be ordered and non-overlapping",
                        )
                    )
                train = set(range(fold["train_start"], fold["train_end"]))
                test = set(range(fold["test_start"], fold["test_end"]))
                expected_purged = list(
                    range(
                        max(
                            fold["train_end"],
                            fold["test_start"]
                            - document["validation"]["purge_observations"],
                        ),
                        fold["test_start"],
                    )
                )
                expected_embargoed = list(
                    range(
                        fold["test_end"],
                        fold["test_end"]
                        + document["validation"]["embargo_observations"],
                    )
                )
                observed_embargoed = fold["embargoed"]
                embargo_matches = (
                    observed_embargoed == expected_embargoed
                    if index < len(folds) - 1
                    else observed_embargoed
                    == expected_embargoed[: len(observed_embargoed)]
                    and len(observed_embargoed)
                    <= document["validation"]["embargo_observations"]
                )
                purged = set(fold["purged"])
                embargoed = set(observed_embargoed)
                if (
                    fold["purged"] != expected_purged
                    or not embargo_matches
                    or train & test
                    or train & purged
                    or train & embargoed
                    or test & purged
                    or test & embargoed
                    or purged & embargoed
                ):
                    issues.append(
                        ValidationIssue(
                            f"$.validation.folds[{index}]",
                            "purge and embargo indices must exactly match the registered non-overlapping policy",
                        )
                    )
                if index and fold["test_start"] < (
                    folds[index - 1]["test_end"]
                    + len(folds[index - 1]["embargoed"])
                ):
                    issues.append(
                        ValidationIssue(
                            f"$.validation.folds[{index}].test_start",
                            "test folds must advance beyond the prior test and embargo",
                        )
                    )
        holdout = require_ordered_interval(
            document["validation"]["holdout_start_time"],
            document["validation"]["holdout_end_time"],
            "$.validation.holdout",
            issues,
        )
        if holdout is None:
            issues.append(
                ValidationIssue(
                    "$.validation.holdout",
                    "robustness holdout must be an ordered RFC3339 interval",
                )
            )
        failed_cells = sum(
            1 for cell in cells if isinstance(cell, dict) and cell.get("status") != "complete"
        )
        if document["failed_cells"] != failed_cells:
            issues.append(
                ValidationIssue(
                    "$.failed_cells", "must equal the number of non-complete cells"
                )
            )

        if not issues and failed_cells == 0:
            complete_matrix = [[float(value) for value in row] for row in matrix]
            selected = [row[selected_index] for row in complete_matrix]
            baseline = [row[null_index] for row in complete_matrix]
            selected_mean = sum(selected) / len(selected)
            baseline_mean = sum(baseline) / len(baseline)
            if (
                not math.isclose(
                    document["null_baseline"]["selected_mean_return"],
                    selected_mean,
                    rel_tol=1e-12,
                    abs_tol=1e-15,
                )
                or not math.isclose(
                    document["null_baseline"]["baseline_mean_return"],
                    baseline_mean,
                    rel_tol=1e-12,
                    abs_tol=1e-15,
                )
                or document["null_baseline"]["status"]
                != ("pass" if selected_mean > baseline_mean else "blocked")
            ):
                issues.append(
                    ValidationIssue(
                        "$.null_baseline",
                        "must be derived from selected and preregistered null returns",
                    )
                )
            expected_neighbors = [
                index
                for index in (selected_index - 1, selected_index + 1)
                if 0 <= index < len(variants) and index != null_index
            ]
            neighbor_means = [
                sum(row[index] for row in complete_matrix) / len(complete_matrix)
                for index in expected_neighbors
            ]
            worst_neighbor = min(neighbor_means) if neighbor_means else None
            stability = document["parameter_stability"]
            observed_worst = stability["worst_neighbor_return"]
            worst_matches = (
                worst_neighbor is None
                and observed_worst is None
                or is_finite_number(observed_worst)
                and worst_neighbor is not None
                and math.isclose(
                    observed_worst,
                    worst_neighbor,
                    rel_tol=1e-12,
                    abs_tol=1e-15,
                )
            )
            expected_stability = (
                "pass"
                if expected_neighbors
                and worst_neighbor is not None
                and worst_neighbor > 0
                else "blocked"
            )
            if (
                stability["neighbor_indices"] != expected_neighbors
                or not worst_matches
                or stability["status"] != expected_stability
            ):
                issues.append(
                    ValidationIssue(
                        "$.parameter_stability",
                        "must be derived from registered neighboring variants",
                    )
                )
            trial_sharpes = []
            for column in range(len(variants)):
                values = [row[column] for row in complete_matrix]
                average = sum(values) / len(values)
                variance = sum((value - average) ** 2 for value in values) / max(
                    1, len(values) - 1
                )
                trial_sharpes.append(average / variance**0.5 if variance else 0.0)
            blocks = document["validation"]["cscv_blocks"]
            expected_statistics = {
                "pbo": cscv_pbo(complete_matrix, blocks=blocks),
                "psr": probabilistic_sharpe_ratio(selected),
                "dsr": deflated_sharpe_ratio(
                    selected, trial_sharpes=trial_sharpes
                ),
                "reality_check": reality_check(
                    complete_matrix, bootstrap_samples=500, seed=7
                ),
            }
            for field, expected in expected_statistics.items():
                observed = document["statistics"].get(field)
                if isinstance(expected, dict):
                    if observed != expected:
                        issues.append(
                            ValidationIssue(
                                f"$.statistics.{field}",
                                "does not match recomputation from the registered matrix",
                            )
                        )
                elif not is_finite_number(observed) or not math.isclose(
                    observed, expected, rel_tol=1e-12, abs_tol=1e-15
                ):
                    issues.append(
                        ValidationIssue(
                            f"$.statistics.{field}",
                            "does not match recomputation from the registered matrix",
                        )
                    )

        from ..robustness import MANDATORY_STRESS_SCENARIOS

        mandatory_stress = set(MANDATORY_STRESS_SCENARIOS)
        stress_names = {
            row["scenario"] for row in document["stress_results"]
        }
        if len(stress_names) != len(document["stress_results"]):
            issues.append(
                ValidationIssue(
                    "$.stress_results",
                    "stress scenario names must be unique",
                )
            )
        promotion_conditions = (
            document["status"] == "complete"
            and failed_cells == 0
            and isinstance(document["source_package_id"], str)
            and document["validation"]["mode"] == "purged_walk_forward"
            and document["null_baseline"]["status"] == "pass"
            and document["parameter_stability"]["status"] == "pass"
            and bool(document["stress_results"])
            and mandatory_stress <= stress_names
            and all(row["status"] == "pass" for row in document["stress_results"])
            and all(
                cell.get("runtime_promotion_eligible") is True
                for cell in cells
                if isinstance(cell, dict)
            )
        )
        if document["promotion_eligible"] != promotion_conditions:
            issues.append(
                ValidationIssue(
                    "$.promotion_eligible",
                    "must be derived from complete purged walk-forward, runtime, baseline, stress, and stability evidence",
                )
            )

    if artifact_type == "screen_report":
        decision = document["decision"]
        if (
            decision["status"] == "backtest_candidate"
            and not document["variants"]["tried"]
        ):
            issues.append(
                ValidationIssue(
                    "$.variants.tried", "must record at least one tried variant"
                )
            )

    if artifact_type == "findings":
        summary = document["summary"]
        blocking = [
            finding
            for finding in document["findings"]
            if finding["blocks_promotion"]
            and finding["status"] in {"open", "confirmed"}
        ]
        if summary["gate_result"] == "pass" and blocking:
            issues.append(
                ValidationIssue(
                    "$.summary.gate_result",
                    "cannot pass with unresolved blocking findings",
                )
            )

    if artifact_type == "simmer_laps":
        if len(document["laps"]) > document["budget"]["max_laps"]:
            issues.append(ValidationIssue("$.laps", "cannot exceed budget.max_laps"))
        lap_numbers = [lap["lap"] for lap in document["laps"]]
        if lap_numbers != list(range(1, len(lap_numbers) + 1)):
            issues.append(
                ValidationIssue(
                    "$.laps", "lap numbers must be contiguous and start at 1"
                )
            )
        movement = [lap["moved_gate"] for lap in document["laps"]]
        if document["final"]["status"] == "passed" and not any(movement):
            issues.append(
                ValidationIssue(
                    "$.final.status", "cannot pass when no lap moved the target gate"
                )
            )
        if any(
            not movement[index] and not movement[index + 1]
            for index in range(len(movement) - 1)
        ):
            issues.append(
                ValidationIssue(
                    "$.laps", "must stop after two consecutive no-progress laps"
                )
            )

    if artifact_type == "paper_plan":
        decision_logic = document["decision_logic"]
        if not decision_logic["same_as_backtest"] and not decision_logic["differences"]:
            issues.append(
                ValidationIssue(
                    "$.decision_logic.differences",
                    "must document differences when paper logic differs from backtest",
                )
            )

    if artifact_type == "divergence_report":
        blocking_breaches = [
            breach for breach in document["breaches"] if breach["blocks_promotion"]
        ]
        if (
            document["decision"]["status"] == "risk_review_candidate"
            and blocking_breaches
        ):
            issues.append(
                ValidationIssue(
                    "$.decision.status",
                    "cannot be risk_review_candidate while a blocking divergence breach exists",
                )
            )

    if artifact_type == "receipt_summary":
        if document["summary"]["entries"] != len(document["packages"]):
            issues.append(
                ValidationIssue(
                    "$.summary.entries", "must equal the number of package rows"
                )
            )

    return issues

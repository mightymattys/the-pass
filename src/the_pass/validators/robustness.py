"""Version 3 robustness evidence recomputation."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

from .common import is_finite_number
from .models import ValidationIssue
from .registry import load_document, repo_root_from
from .robustness_evidence import validate_evidence_binding
from .robustness_registration import validate_registration_policy_and_ledger

def validate_robustness_report_v3(
    document: dict[str, Any],
    *,
    ledger_path: Path | None = None,
    artifact_path: Path | None = None,
) -> list[ValidationIssue]:
    """Recompute train selection and all OOS robustness evidence."""

    from ..robustness import (
        cscv_pbo,
        deflated_sharpe_ratio,
        effective_sample_size,
        MANDATORY_STRESS_SCENARIOS,
        mean_difference_permutation_pvalue,
        probabilistic_sharpe_ratio_effective,
        reality_check,
        run_stress_suite,
        select_train_winner,
        stress_parameters_from_cost_waterfall,
    )

    issues: list[ValidationIssue] = []
    (
        registration,
        variants,
        variant_count,
        null_index,
        null_kind,
        structural_null_valid,
        packaged_thresholds,
        policy_binding_valid,
        reported_thresholds,
        effective_trial_count,
        ledger_registration_valid,
    ) = validate_registration_policy_and_ledger(document, ledger_path, issues)
    folds = document["validation"]["folds"]
    for index, fold in enumerate(folds):
        if fold["id"] != index:
            issues.append(
                ValidationIssue(
                    f"$.validation.folds[{index}].id",
                    "fold IDs must be contiguous and match result order",
                )
            )
        if not (
            fold["train_start"]
            < fold["train_end"]
            <= fold["test_start"]
            < fold["test_end"]
        ):
            issues.append(
                ValidationIssue(
                    f"$.validation.folds[{index}]",
                    "train and test intervals must be ordered and non-overlapping",
                )
            )
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
        if fold["purged"] != expected_purged:
            issues.append(
                ValidationIssue(
                    f"$.validation.folds[{index}].purged",
                    "must exactly match the registered purge policy",
                )
            )
        expected_embargo = list(
            range(
                fold["test_end"],
                fold["test_end"]
                + document["validation"]["embargo_observations"],
            )
        )
        observed_embargo = fold["embargoed"]
        embargo_matches = (
            observed_embargo == expected_embargo
            if index < len(folds) - 1
            else observed_embargo == expected_embargo[: len(observed_embargo)]
            and len(observed_embargo)
            <= document["validation"]["embargo_observations"]
        )
        if not embargo_matches:
            issues.append(
                ValidationIssue(
                    f"$.validation.folds[{index}].embargoed",
                    "must exactly match the registered embargo policy",
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

    cells = document["cells"]
    cell_map: dict[tuple[int, str, int], dict[str, Any]] = {}
    for index, cell in enumerate(cells):
        key = (cell["fold_id"], cell["phase"], cell["variant_index"])
        if key in cell_map:
            issues.append(
                ValidationIssue(
                    f"$.cells[{index}]",
                    "duplicates a fold, phase, and variant cell",
                )
            )
            continue
        cell_map[key] = cell
        if (
            cell["fold_id"] >= len(folds)
            or cell["variant_index"] >= variant_count
        ):
            issues.append(
                ValidationIssue(
                    f"$.cells[{index}]",
                    "references an unknown fold or variant",
                )
            )
            continue
        if cell["status"] == "complete":
            if (
                not is_finite_number(cell["net_return"])
                or not cell["periodic_returns"]
                or cell["result_fingerprint"] is None
                or any(
                    not is_finite_number(value)
                    for value in cell["periodic_returns"]
                )
            ):
                issues.append(
                    ValidationIssue(
                        f"$.cells[{index}]",
                        "complete cells require finite return evidence and a result fingerprint",
                    )
                )
            else:
                compounded = math.prod(
                    1 + float(value) for value in cell["periodic_returns"]
                ) - 1
                if not math.isclose(
                    float(cell["net_return"]),
                    compounded,
                    rel_tol=1e-10,
                    abs_tol=1e-12,
                ):
                    issues.append(
                        ValidationIssue(
                            f"$.cells[{index}].net_return",
                            "must equal compounded periodic returns",
                        )
                    )
        elif (
            cell["net_return"] is not None
            or cell["periodic_returns"]
            or cell["result_fingerprint"] is not None
            or cell["runtime_promotion_eligible"]
        ):
            issues.append(
                ValidationIssue(
                    f"$.cells[{index}]",
                    "failed cells must not contain successful return or runtime evidence",
                )
            )

    expected_cell_count = len(folds) * variant_count * 2
    if len(cell_map) != expected_cell_count:
        issues.append(
            ValidationIssue(
                "$.cells",
                "must contain exactly one train and test cell per fold and variant",
            )
        )

    fold_results = document["fold_results"]
    variant_oos_returns: list[list[float]] = [
        [] for _variant in variants
    ]
    selected_oos_returns: list[float] = []
    null_oos_returns: list[float] = []
    fold_neighbor_returns: list[float] = []
    neighbor_indices: set[int] = set()
    alignment_failed = False
    for fold_index in range(len(folds)):
        try:
            train_cells = [
                cell_map[(fold_index, "train", variant)]
                for variant in range(variant_count)
            ]
            test_cells = [
                cell_map[(fold_index, "test", variant)]
                for variant in range(variant_count)
            ]
        except KeyError:
            alignment_failed = True
            continue
        train_complete = all(
            cell["status"] == "complete" for cell in train_cells
        )
        selected = (
            select_train_winner(
                [float(cell["net_return"]) for cell in train_cells],
                excluded_indices=(null_index,),
            )
            if train_complete
            else None
        )
        observed_fold = fold_results[fold_index]
        expected_train = (
            train_cells[selected]["net_return"] if selected is not None else None
        )
        expected_test = (
            test_cells[selected]["net_return"]
            if selected is not None
            and test_cells[selected]["status"] == "complete"
            else None
        )
        if (
            observed_fold["fold_id"] != fold_index
            or observed_fold["selected_variant_index"] != selected
            or observed_fold["selected_train_score"] != expected_train
            or observed_fold["selected_test_return"] != expected_test
        ):
            issues.append(
                ValidationIssue(
                    f"$.fold_results[{fold_index}]",
                    "must be derived only from deterministic train-cell selection",
                )
            )
        test_complete = all(
            cell["status"] == "complete" for cell in test_cells
        )
        lengths = {
            len(cell["periodic_returns"]) for cell in test_cells
        }
        if not test_complete or len(lengths) != 1:
            alignment_failed = True
            continue
        for variant, cell in enumerate(test_cells):
            variant_oos_returns[variant].extend(
                float(value) for value in cell["periodic_returns"]
            )
        if selected is None:
            alignment_failed = True
            continue
        selected_oos_returns.extend(
            float(value) for value in test_cells[selected]["periodic_returns"]
        )
        null_oos_returns.extend(
            float(value)
            for value in test_cells[null_index]["periodic_returns"]
        )
        fold_neighbors = []
        for neighbor in (selected - 1, selected + 1):
            if 0 <= neighbor < variant_count and neighbor != null_index:
                neighbor_indices.add(neighbor)
                fold_neighbors.append(
                    float(test_cells[neighbor]["net_return"])
                )
        if fold_neighbors:
            fold_neighbor_returns.append(min(fold_neighbors))

    non_complete = sum(
        cell["status"] != "complete" for cell in cells
    )
    expected_failed = non_complete + int(alignment_failed)
    if document["failed_cells"] != expected_failed:
        issues.append(
            ValidationIssue(
                "$.failed_cells",
                "must equal failed cells plus any OOS alignment failure",
            )
        )
    expected_status = (
        "blocked" if non_complete or alignment_failed else "complete"
    )
    if document["status"] != expected_status:
        issues.append(
            ValidationIssue(
                "$.status",
                "must be derived from complete and aligned train/test cells",
            )
        )

    expected_matrix = (
        [
            [
                variant_oos_returns[column][row]
                for column in range(variant_count)
            ]
            for row in range(len(selected_oos_returns))
        ]
        if not alignment_failed
        and len({len(values) for values in variant_oos_returns}) == 1
        else []
    )
    if document["oos_matrix"] != expected_matrix:
        issues.append(
            ValidationIssue(
                "$.oos_matrix",
                "must be the aligned periodic OOS return matrix for all variants",
            )
        )
    if document["selected_oos_returns"] != selected_oos_returns:
        issues.append(
            ValidationIssue(
                "$.selected_oos_returns",
                "must stitch only each fold's train-selected test returns",
            )
        )

    complete_statistics = (
        not alignment_failed
        and not non_complete
        and len(selected_oos_returns) >= 4
        and bool(expected_matrix)
    )
    expected_statistics = document["statistics"]
    if complete_statistics:
        expected_sample = effective_sample_size(selected_oos_returns)
        if document["sample"] != expected_sample:
            issues.append(
                ValidationIssue(
                    "$.sample",
                    "must reflect autocorrelation-adjusted selected OOS observations",
                )
            )
        trial_sharpes = []
        for values in variant_oos_returns:
            average = sum(values) / len(values)
            variance = sum(
                (value - average) ** 2 for value in values
            ) / max(1, len(values) - 1)
            trial_sharpes.append(
                average / variance**0.5 if variance else 0.0
            )
        blocks = min(8, len(expected_matrix))
        blocks -= blocks % 2
        expected_statistics = {
            "pbo": cscv_pbo(expected_matrix, blocks=blocks),
            "psr": probabilistic_sharpe_ratio_effective(
                selected_oos_returns,
                effective_observations=expected_sample[
                    "effective_observations"
                ],
            ),
            "dsr": deflated_sharpe_ratio(
                selected_oos_returns,
                trial_sharpes=trial_sharpes,
                effective_observations=expected_sample[
                    "effective_observations"
                ],
                effective_trial_count=effective_trial_count,
            ),
            "reality_check": reality_check(
                expected_matrix,
                bootstrap_samples=500,
                seed=7,
            ),
            "thresholds": reported_thresholds,
            "effective_trial_count": effective_trial_count,
        }
        if document["statistics"] != expected_statistics:
            issues.append(
                ValidationIssue(
                    "$.statistics",
                    "does not match recomputation from aligned OOS periodic returns",
                )
            )
        if document["validation"]["cscv_blocks"] != blocks:
            issues.append(
                ValidationIssue(
                    "$.validation.cscv_blocks",
                    "must match the deterministic OOS CSCV block count",
                )
            )
    else:
        expected_sample = document["sample"]

    selected_mean = (
        sum(selected_oos_returns) / len(selected_oos_returns)
        if selected_oos_returns
        else 0.0
    )
    null_mean = (
        sum(null_oos_returns) / len(null_oos_returns)
        if null_oos_returns
        else 0.0
    )
    if null_kind == "flat":
        null_cells = [
            cell
            for cell in cells
            if cell["variant_index"] == null_index
        ]
        null_cell_means = [
            sum(float(value) for value in cell["periodic_returns"])
            / len(cell["periodic_returns"])
            for cell in null_cells
            if cell["status"] == "complete" and cell["periodic_returns"]
        ]
        diagnostic_passed = (
            "pass"
            if structural_null_valid
            and bool(null_cell_means)
            and len(null_cell_means) == len(null_cells)
            and all(abs(value) <= 1e-12 for value in null_cell_means)
            else "blocked"
        )
        exact_passed = structural_null_valid and bool(null_cells) and all(
            cell["status"] == "complete"
            and bool(cell["periodic_returns"])
            and all(float(value) == 0.0 for value in cell["periodic_returns"])
            for cell in null_cells
        )
        null_structure_status = "pass" if exact_passed else "blocked"
        expected_structure = {
            "status": null_structure_status,
            "check": "every_complete_cell_periodic_return_exactly_zero",
            "tolerance": 0.0,
            "diagnostic": {
                "check": "each_cell_mean_net_return_near_zero",
                "tolerance": 1e-12,
                "status": diagnostic_passed,
            },
            "limitation": "the tolerance check is diagnostic only; promotion requires every periodic return to equal exactly 0.0",
        }
    else:
        null_structure_status = "blocked"
        expected_structure = {
            "status": null_structure_status,
            "check": "seed_registered_and_strategy_keys_disjoint_from_reference",
            "tolerance": None,
            "diagnostic": {
                "check": "registered_seed_and_disjoint_strategy_keys",
                "tolerance": None,
                "status": "pass" if structural_null_valid else "blocked",
            },
            "limitation": "seeded_random nulls are diagnostic only and cannot support promotion until a trusted framework-side generator exists",
        }
    null_test = (
        mean_difference_permutation_pvalue(
            selected_oos_returns,
            null_oos_returns,
            samples=2000,
            seed=7,
        )
        if complete_statistics
        else {"pvalue": 1.0, "block_length": 1}
    )
    null_pvalue = float(null_test["pvalue"])
    null_status = (
        "pass"
        if complete_statistics
        and null_structure_status == "pass"
        and null_pvalue <= 0.10
        else "blocked"
    )
    baseline = document["null_baseline"]
    if (
        baseline["variant_index"] != null_index
        or not math.isclose(
            baseline["selected_mean_return"],
            selected_mean,
            rel_tol=1e-12,
            abs_tol=1e-15,
        )
        or not math.isclose(
            baseline["baseline_mean_return"],
            null_mean,
            rel_tol=1e-12,
            abs_tol=1e-15,
        )
        or not math.isclose(
            baseline.get("pvalue", -1),
            null_pvalue,
            rel_tol=1e-12,
            abs_tol=1e-15,
        )
        or baseline.get("test")
        != "paired_one_sided_circular_block_sign_flip_mean_difference"
        or baseline.get("block_length") != null_test["block_length"]
        or baseline.get("structure") != expected_structure
        or baseline["status"] != null_status
    ):
        issues.append(
            ValidationIssue(
                "$.null_baseline",
                "must statistically compare aligned OOS returns and verify the structural null",
            )
        )

    worst_neighbor = (
        min(fold_neighbor_returns) if fold_neighbor_returns else None
    )
    stability_status = (
        "pass"
        if complete_statistics
        and len(fold_neighbor_returns) == len(folds)
        and worst_neighbor is not None
        and worst_neighbor > 0
        else "blocked"
    )
    stability = document["parameter_stability"]
    observed_worst = stability["worst_neighbor_return"]
    worst_matches = (
        worst_neighbor is None
        and observed_worst is None
        or worst_neighbor is not None
        and is_finite_number(observed_worst)
        and math.isclose(
            float(observed_worst),
            worst_neighbor,
            rel_tol=1e-12,
            abs_tol=1e-15,
        )
    )
    if (
        stability["neighbor_indices"] != sorted(neighbor_indices)
        or not worst_matches
        or stability["status"] != stability_status
    ):
        issues.append(
            ValidationIssue(
                "$.parameter_stability",
                "must be derived from each train-selected variant's OOS neighbors",
            )
        )

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
    cost_sourced = bool(document["stress_results"]) and all(
        row.get("inputs_source") == "cost_waterfall"
        for row in document["stress_results"]
    )
    stress_recomputed = False
    if cost_sourced:
        evidence = document.get("stress_evidence")
        if not isinstance(evidence, dict):
            issues.append(
                ValidationIssue(
                    "$.stress_evidence",
                    "cost-waterfall stress rows require source package evidence",
                )
            )
        else:
            source_value = Path(evidence["source_package_path"])
            source_package = (
                source_value.resolve()
                if source_value.is_absolute()
                else (repo_root_from(artifact_path) / source_value).resolve()
            )
            cost_path = source_package / "cost_waterfall.json"
            same_source_package = (
                artifact_path is not None and source_package == artifact_path.parent
            )
            if same_source_package:
                issues.append(
                    ValidationIssue(
                        "$.stress_evidence.source_package_path",
                        "stress source package must be separate from the robustness report package",
                    )
                )
                cost_sourced = False
            try:
                cost_bytes = cost_path.read_bytes()
                cost_document = json.loads(cost_bytes)
            except (OSError, json.JSONDecodeError) as exc:
                issues.append(
                    ValidationIssue(
                        "$.stress_evidence.source_package_path",
                        f"cannot read source cost waterfall: {exc}",
                    )
                )
            else:
                stress_source_bound = False
                expected_hash = hashlib.sha256(cost_bytes).hexdigest()
                if evidence.get("cost_waterfall_sha256") != expected_hash:
                    issues.append(
                        ValidationIssue(
                            "$.stress_evidence.cost_waterfall_sha256",
                            "does not match source package cost evidence",
                        )
                    )
                try:
                    from ..ledger import LedgerError, build_run_entry

                    if same_source_package:
                        raise ValueError("stress source is the report package")
                    source_entry = build_run_entry(source_package)
                    run_receipt = load_document(source_package / "run_receipt.json")
                    linked_cost = (
                        source_package
                        / str(run_receipt.get("outputs", {}).get("cost_waterfall", ""))
                    ).resolve()
                    linked_receipt = (
                        source_package / str(cost_document.get("run_receipt", ""))
                    ).resolve()
                    stress_source_bound = (
                        source_entry.get("package_id")
                        == document.get("source_package_id")
                        == evidence.get("source_package_id")
                        and linked_cost == cost_path.resolve()
                        and linked_receipt
                        == (source_package / "run_receipt.json").resolve()
                    )
                except (OSError, ValueError, TypeError, KeyError, LedgerError) as exc:
                    issues.append(
                        ValidationIssue(
                            "$.stress_evidence.source_package_id",
                            f"cannot verify source package identity: {exc}",
                        )
                    )
                    stress_source_bound = False
                if not stress_source_bound:
                    issues.append(
                        ValidationIssue(
                            "$.stress_evidence.source_package_id",
                            "cost waterfall and run receipt must bind the report source_package_id",
                        )
                    )
                expected_rows = [
                    {
                        key: row[key]
                        for key in (
                            "scenario",
                            "status",
                            "net_pnl",
                            "summary",
                            "inputs_source",
                            "formula",
                        )
                    }
                    for row in run_stress_suite(
                        stress_parameters_from_cost_waterfall(
                            cost_document, selected_oos_returns
                        )
                    )
                ]
                if document["stress_results"] != expected_rows:
                    issues.append(
                        ValidationIssue(
                            "$.stress_results",
                            "does not match recomputation from the source cost waterfall and selected OOS returns",
                        )
                    )
                elif (
                    evidence.get("cost_waterfall_sha256") == expected_hash
                    and stress_source_bound
                ):
                    stress_recomputed = True
    elif document.get("promotion_eligible") is True:
        issues.append(
            ValidationIssue(
                "$.stress_results",
                "promotion-eligible reports cannot use caller-sourced stress rows",
            )
        )

    recomputed_pbo = (
        expected_statistics["pbo"]["pbo"] if complete_statistics else 1.0
    )
    recomputed_dsr = expected_statistics["dsr"] if complete_statistics else 0.0
    recomputed_reality_pvalue = (
        expected_statistics["reality_check"]["reality_check_pvalue"]
        if complete_statistics
        else 1.0
    )
    threshold_conditions = (
        recomputed_pbo <= packaged_thresholds["maximum_pbo"]
        and recomputed_dsr >= packaged_thresholds["minimum_dsr"]
        and recomputed_reality_pvalue
        <= packaged_thresholds["maximum_reality_check_pvalue"]
    )
    if document.get("promotion_eligible") is True:
        if recomputed_pbo > packaged_thresholds["maximum_pbo"]:
            issues.append(
                ValidationIssue(
                    "$.promotion_eligible",
                    f"cannot be true: recomputed PBO {recomputed_pbo:.12g} exceeds policy maximum {packaged_thresholds['maximum_pbo']:.12g}",
                )
            )
        if recomputed_dsr < packaged_thresholds["minimum_dsr"]:
            issues.append(
                ValidationIssue(
                    "$.promotion_eligible",
                    f"cannot be true: recomputed DSR {recomputed_dsr:.12g} is below policy minimum {packaged_thresholds['minimum_dsr']:.12g}",
                )
            )
        if recomputed_reality_pvalue > packaged_thresholds["maximum_reality_check_pvalue"]:
            issues.append(
                ValidationIssue(
                    "$.promotion_eligible",
                    "cannot be true: recomputed Reality Check p-value "
                    f"{recomputed_reality_pvalue:.12g} exceeds policy maximum "
                    f"{packaged_thresholds['maximum_reality_check_pvalue']:.12g}",
                )
            )
    evidence_binding_valid = validate_evidence_binding(
        document,
        artifact_path,
        registration,
        expected_statistics,
        cells,
        selected_oos_returns,
        issues,
    )
    promotion_conditions = (
        document["status"] == "complete"
        and document["validation"]["mode"] == "purged_walk_forward"
        and complete_statistics
        and expected_sample.get("effective_observations", 0) >= 30
        and threshold_conditions
        and policy_binding_valid
        and null_kind == "flat"
        and null_status == "pass"
        and stability_status == "pass"
        and mandatory_stress <= stress_names
        and cost_sourced
        and stress_recomputed
        and all(
            row["status"] == "pass"
            for row in document["stress_results"]
        )
        and all(
            cell["runtime_promotion_eligible"]
            and cell["execution_schema_version"] == 2
            for cell in cells
        )
        and isinstance(document["source_package_id"], str)
        and ledger_registration_valid
        and evidence_binding_valid
    )
    if document["promotion_eligible"] != promotion_conditions:
        issues.append(
            ValidationIssue(
                "$.promotion_eligible",
                "must be derived from policy-thresholded statistics, ledger-backed trials, structural null, evidence-derived stress, execution v2, and runtime evidence",
            )
        )
    return issues

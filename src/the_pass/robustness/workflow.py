"""Strategy-driven, preregistered robustness matrix generation."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from the_pass.data.contracts import CanonicalEvent, stable_fingerprint
from the_pass.strategy_runtime import (
    parse_execution_config,
    parse_strategy_descriptor,
    run_strategy_verified,
)

from .statistics import (
    cscv_pbo,
    deflated_sharpe_ratio,
    probabilistic_sharpe_ratio,
    purged_walk_forward_splits,
    reality_check,
)


def _persist_registration(path: Path, registration: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(registration, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("utf-8")
    try:
        with path.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError as exc:
        raise FileExistsError(
            f"robustness registration is create-only and already exists: {path}"
        ) from exc


def run_strategy_sweep(
    events: Sequence[CanonicalEvent],
    *,
    descriptor: Mapping[str, Any],
    execution: Mapping[str, Any],
    variants: Sequence[Mapping[str, Any]],
    splits: Sequence[Mapping[str, int]] | None,
    selected_index: int,
    registration_path: Path,
    workspace_root: Path,
    timeout_seconds: float = 60.0,
    source_package_id: str | None = None,
    created_at: str | None = None,
    train_size: int | None = None,
    test_size: int | None = None,
    purge: int = 0,
    embargo: int = 0,
    null_variant_index: int | None = None,
    stress_results: Sequence[Mapping[str, Any]] = (),
    runtime_mode: str = "trusted_local",
    sandbox_launcher: Path | None = None,
    sandbox_policy: Path | None = None,
) -> dict[str, Any]:
    """Execute every preregistered variant/split; failed cells remain evidence."""

    rows = sorted(events, key=CanonicalEvent.sort_key)
    if len(variants) < 2:
        raise ValueError("robustness sweep requires at least two variants")
    if not 0 <= selected_index < len(variants):
        raise ValueError("selected_index is outside the preregistered variants")
    normalized_folds: list[dict[str, Any]] = []
    validation_mode = "diagnostic_splits"
    if train_size is not None or test_size is not None:
        if splits is not None:
            raise ValueError("use explicit splits or generated walk-forward, not both")
        if train_size is None or test_size is None:
            raise ValueError("walk-forward requires both train_size and test_size")
        validation_mode = "purged_walk_forward"
        generated = purged_walk_forward_splits(
            len(rows),
            train_size=train_size,
            test_size=test_size,
            purge=purge,
            embargo=embargo,
            anchored=True,
        )
        for index, fold in enumerate(generated):
            normalized_folds.append(
                {
                    "id": index,
                    "train_start": fold.train[0],
                    "train_end": fold.train[-1] + 1,
                    "test_start": fold.test[0],
                    "test_end": fold.test[-1] + 1,
                    "purged": list(fold.purged),
                    "embargoed": list(fold.embargoed),
                }
            )
    else:
        if splits is None:
            raise ValueError("diagnostic sweep requires splits")
        previous_end = 0
        for index, split in enumerate(splits):
            if set(split) != {"start", "end"}:
                raise ValueError("each split must contain only start and end indexes")
            start, end = int(split["start"]), int(split["end"])
            if start < previous_end or start < 0 or end <= start or end > len(rows):
                raise ValueError(
                    "splits must be ordered, non-overlapping, and inside events"
                )
            if end - start < 2:
                raise ValueError("each robustness split requires at least two events")
            normalized_folds.append(
                {
                    "id": index,
                    "train_start": 0,
                    "train_end": max(1, start),
                    "test_start": start,
                    "test_end": end,
                    "purged": [],
                    "embargoed": [],
                }
            )
            previous_end = end
    if len(normalized_folds) < 4:
        raise ValueError("robustness sweep requires at least four splits")
    if null_variant_index is None:
        null_variant_index = len(variants) - 1
    if not 0 <= null_variant_index < len(variants):
        raise ValueError("null_variant_index is outside the preregistered variants")
    if null_variant_index == selected_index:
        raise ValueError("null baseline variant must differ from the selected variant")
    parsed_descriptor = parse_strategy_descriptor(
        descriptor,
        workspace_root=workspace_root,
    )
    parsed_execution = parse_execution_config(execution)
    registration_core = {
        "schema_version": 2,
        "descriptor_fingerprint": parsed_descriptor.descriptor_fingerprint,
        "strategy_source_sha256": parsed_descriptor.source_sha256,
        "execution_fingerprint": parsed_execution.fingerprint,
        "events_fingerprint": stable_fingerprint([event.as_dict() for event in rows]),
        "variants": [dict(variant) for variant in variants],
        "selected_index": selected_index,
        "selection_policy": "selected index supplied before any variant execution",
    }
    registration = {
        **registration_core,
        "registration_fingerprint": stable_fingerprint(registration_core),
    }
    _persist_registration(registration_path, registration)
    matrix: list[list[float | None]] = []
    cells = []
    initial_cash = Decimal(str(execution["initial_cash"]))
    for fold in normalized_folds:
        split_rows = rows[fold["test_start"] : fold["test_end"]]
        matrix_row: list[float | None] = []
        for variant_index, variant in enumerate(variants):
            candidate = dict(descriptor)
            candidate["config"] = {**dict(descriptor.get("config", {})), **dict(variant)}
            try:
                result = run_strategy_verified(
                    split_rows,
                    descriptor=candidate,
                    execution=execution,
                    workspace_root=workspace_root,
                    timeout_seconds=timeout_seconds,
                    runtime_mode=runtime_mode,
                    sandbox_launcher=sandbox_launcher,
                    sandbox_policy=sandbox_policy,
                )
                net_return = float(
                    (Decimal(str(result["final_portfolio"]["equity"])) - initial_cash)
                    / initial_cash
                )
                matrix_row.append(net_return)
                cells.append(
                    {
                        "fold_id": fold["id"],
                        "variant_index": variant_index,
                        "status": "complete",
                        "net_return": net_return,
                        "result_fingerprint": result["result_fingerprint"],
                        "runtime_promotion_eligible": result[
                            "runtime_promotion_eligible"
                        ],
                    }
                )
            except Exception as exc:
                matrix_row.append(None)
                cells.append(
                    {
                        "fold_id": fold["id"],
                        "variant_index": variant_index,
                        "status": "failed",
                        "net_return": None,
                        "result_fingerprint": None,
                        "runtime_promotion_eligible": False,
                        "error_type": type(exc).__name__,
                    }
                )
        matrix.append(matrix_row)
    failed = [cell for cell in cells if cell["status"] == "failed"]
    statistics: dict[str, Any] = {
        "pbo": {
            "pbo": 1.0,
            "combinations": 1,
            "logits": [],
            "selected_variants": [],
        },
        "psr": 0.0,
        "dsr": 0.0,
        "reality_check": {"observed_best_mean": 0.0, "p_value": 1.0},
    }
    selected_mean = 0.0
    baseline_mean = 0.0
    neighbor_indices = [
        index
        for index in (selected_index - 1, selected_index + 1)
        if 0 <= index < len(variants) and index != null_variant_index
    ]
    worst_neighbor: float | None = None
    if not failed:
        complete_matrix = [[float(value) for value in row] for row in matrix]
        selected = [row[selected_index] for row in complete_matrix]
        baseline = [row[null_variant_index] for row in complete_matrix]
        selected_mean = sum(selected) / len(selected)
        baseline_mean = sum(baseline) / len(baseline)
        neighbor_means = [
            sum(row[index] for row in complete_matrix) / len(complete_matrix)
            for index in neighbor_indices
        ]
        worst_neighbor = min(neighbor_means) if neighbor_means else None
        trial_sharpes = []
        for column in range(len(variants)):
            values = [row[column] for row in complete_matrix]
            average = sum(values) / len(values)
            variance = sum((value - average) ** 2 for value in values) / max(1, len(values) - 1)
            trial_sharpes.append(average / variance**0.5 if variance else 0.0)
        blocks = len(complete_matrix) if len(complete_matrix) % 2 == 0 else len(complete_matrix) - 1
        statistics = {
            "pbo": cscv_pbo(complete_matrix, blocks=blocks),
            "psr": probabilistic_sharpe_ratio(selected),
            "dsr": deflated_sharpe_ratio(selected, trial_sharpes=trial_sharpes),
            "reality_check": reality_check(complete_matrix, bootstrap_samples=500, seed=7),
        }
    normalized_stress = [
        {
            "scenario": str(row["scenario"]),
            "status": str(row["status"]),
            "net_pnl": float(row["net_pnl"]),
            "summary": str(row["summary"]),
        }
        for row in stress_results
    ]
    null_status = "pass" if not failed and selected_mean > baseline_mean else "blocked"
    stability_status = (
        "pass"
        if not failed and neighbor_indices and worst_neighbor is not None and worst_neighbor > 0
        else "blocked"
    )
    all_runtime_promotional = not failed and all(
        cell["runtime_promotion_eligible"] for cell in cells
    )
    promotion_eligible = (
        validation_mode == "purged_walk_forward"
        and null_status == "pass"
        and stability_status == "pass"
        and bool(normalized_stress)
        and all(row["status"] == "pass" for row in normalized_stress)
        and all_runtime_promotional
    )
    first_holdout = rows[normalized_folds[0]["test_start"]]
    last_holdout = rows[normalized_folds[-1]["test_end"] - 1]

    def timestamp(value: int) -> str:
        return (
            datetime.fromtimestamp(value / 1_000_000_000, tz=timezone.utc)
            .isoformat()
            .replace("+00:00", "Z")
        )

    report = {
        "schema_version": 2,
        "id": f"robustness-{parsed_descriptor.strategy_id}",
        "created_at": created_at or timestamp(rows[-1].receive_time_ns),
        "source_package_id": source_package_id,
        "registration": registration,
        "status": "blocked" if failed else "complete",
        "matrix": matrix,
        "cells": cells,
        "failed_cells": len(failed),
        "statistics": statistics,
        "validation": {
            "mode": validation_mode,
            "purge_observations": purge,
            "embargo_observations": embargo,
            "cscv_blocks": (
                len(matrix) if len(matrix) % 2 == 0 else len(matrix) - 1
            ),
            "holdout_start_time": timestamp(first_holdout.event_time_ns),
            "holdout_end_time": timestamp(last_holdout.event_time_ns + 1),
            "folds": normalized_folds,
        },
        "null_baseline": {
            "variant_index": null_variant_index,
            "status": null_status,
            "selected_mean_return": selected_mean,
            "baseline_mean_return": baseline_mean,
            "summary": (
                "selected variant exceeds the preregistered null variant"
                if null_status == "pass"
                else "selected variant does not exceed the preregistered null variant"
            ),
        },
        "stress_results": normalized_stress,
        "parameter_stability": {
            "status": stability_status,
            "neighbor_indices": neighbor_indices,
            "worst_neighbor_return": worst_neighbor,
            "summary": (
                "registered neighboring variants remain net positive"
                if stability_status == "pass"
                else "registered neighboring variants do not establish positive stability"
            ),
        },
        "promotion_eligible": promotion_eligible,
    }
    report["report_fingerprint"] = stable_fingerprint(report)
    return report

"""Strategy-driven, preregistered robustness matrix generation."""

from __future__ import annotations

import json
import os
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
    splits: Sequence[Mapping[str, int]],
    selected_index: int,
    registration_path: Path,
    workspace_root: Path,
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    """Execute every preregistered variant/split; failed cells remain evidence."""

    rows = sorted(events, key=CanonicalEvent.sort_key)
    if len(variants) < 2:
        raise ValueError("robustness sweep requires at least two variants")
    if not 0 <= selected_index < len(variants):
        raise ValueError("selected_index is outside the preregistered variants")
    normalized_splits = []
    previous_end = 0
    for index, split in enumerate(splits):
        if set(split) != {"start", "end"}:
            raise ValueError("each split must contain only start and end indexes")
        start, end = int(split["start"]), int(split["end"])
        if start < previous_end or start < 0 or end <= start or end > len(rows):
            raise ValueError("splits must be ordered, non-overlapping, and inside events")
        if end - start < 2:
            raise ValueError("each robustness split requires at least two events")
        normalized_splits.append({"id": index, "start": start, "end": end})
        previous_end = end
    if len(normalized_splits) < 4:
        raise ValueError("robustness sweep requires at least four splits")
    parsed_descriptor = parse_strategy_descriptor(
        descriptor,
        workspace_root=workspace_root,
    )
    parsed_execution = parse_execution_config(execution)
    registration_core = {
        "schema_version": 1,
        "descriptor_fingerprint": parsed_descriptor.descriptor_fingerprint,
        "strategy_source_sha256": parsed_descriptor.source_sha256,
        "execution_fingerprint": parsed_execution.fingerprint,
        "events_fingerprint": stable_fingerprint([event.as_dict() for event in rows]),
        "variants": [dict(variant) for variant in variants],
        "splits": normalized_splits,
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
    for split in normalized_splits:
        split_rows = rows[split["start"] : split["end"]]
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
                )
                net_return = float(
                    (Decimal(str(result["final_portfolio"]["equity"])) - initial_cash)
                    / initial_cash
                )
                matrix_row.append(net_return)
                cells.append(
                    {
                        "split_id": split["id"],
                        "variant_index": variant_index,
                        "status": "complete",
                        "net_return": net_return,
                        "result_fingerprint": result["result_fingerprint"],
                    }
                )
            except Exception as exc:
                matrix_row.append(None)
                cells.append(
                    {
                        "split_id": split["id"],
                        "variant_index": variant_index,
                        "status": "failed",
                        "net_return": None,
                        "error_type": type(exc).__name__,
                    }
                )
        matrix.append(matrix_row)
    failed = [cell for cell in cells if cell["status"] == "failed"]
    statistics: dict[str, Any] = {}
    if not failed:
        complete_matrix = [[float(value) for value in row] for row in matrix]
        selected = [row[selected_index] for row in complete_matrix]
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
    report = {
        "schema_version": 1,
        "status": "blocked" if failed else "complete",
        "registration": registration,
        "registration_fingerprint": registration["registration_fingerprint"],
        "matrix": matrix,
        "cells": cells,
        "failed_cells": len(failed),
        "statistics": statistics,
    }
    report["report_fingerprint"] = stable_fingerprint(report)
    return report

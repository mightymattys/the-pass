"""Credential-free subprocess worker for custom strategy replay."""

from __future__ import annotations

import json
import os
import resource
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from the_pass.data.contracts import CanonicalEvent, canonical_value, stable_fingerprint
from the_pass.engine.costs import LinearCostModel
from the_pass.engine.fills import (
    BarFillModel,
    DiagnosticMidpointFillModel,
    LimitEvidenceFillModel,
    MarketDepthFillModel,
)
from the_pass.engine.simulator import EventSimulator
from the_pass.risk import VersionedRiskPolicy
from the_pass.safety import is_sensitive_key

from .config import ExecutionConfig, load_json_object, parse_execution_config, parse_strategy_descriptor
from .loader import (
    block_forbidden_imports,
    build_strategy,
    forbidden_modules_loaded,
    purge_forbidden_modules,
)


DIAGNOSTIC_RISK_POLICY = {"schema_version": 1, "policy_id": "diagnostic_allow_all_v1"}


def _build_fill_model(config: ExecutionConfig) -> Any:
    if config.fill_model == "bar_next_open":
        return BarFillModel(slippage_bps=config.slippage_bps)
    if config.fill_model == "market_depth":
        return MarketDepthFillModel()
    if config.fill_model == "limit_evidence":
        return LimitEvidenceFillModel(
            queue_haircut=config.queue_haircut,
            adverse_selection_haircut=config.adverse_selection_haircut,
        )
    if config.fill_model == "diagnostic_midpoint":
        return DiagnosticMidpointFillModel()
    raise ValueError("unsupported fill model")


def _serialize_rows(rows: Sequence[Any]) -> list:
    return [canonical_value(asdict(row), allow_float=True) for row in rows]


def execute_request(request: Mapping[str, Any]) -> Dict[str, Any]:
    if set(request) != {
        "schema_version",
        "workspace_root",
        "descriptor",
        "execution",
        "risk_policy",
        "events",
    }:
        raise ValueError("worker request fields are invalid")
    if request["schema_version"] != 1 or isinstance(request["schema_version"], bool):
        raise ValueError("worker request schema_version must be 1")
    descriptor = parse_strategy_descriptor(
        request["descriptor"], workspace_root=Path(str(request["workspace_root"]))
    )
    execution = parse_execution_config(request["execution"])
    risk_document = request["risk_policy"]
    if not isinstance(risk_document, dict):
        raise ValueError("worker risk_policy must be an object")
    if risk_document == DIAGNOSTIC_RISK_POLICY:
        risk_policy = None
    elif risk_document.get("schema_version") == 2:
        risk_policy = VersionedRiskPolicy.from_artifact(risk_document)
    else:
        raise ValueError("worker risk_policy is not supported")
    event_documents = request["events"]
    if not isinstance(event_documents, list) or not event_documents:
        raise ValueError("worker request requires a non-empty event list")
    events = sorted(
        (CanonicalEvent.from_dict(document) for document in event_documents),
        key=CanonicalEvent.sort_key,
    )

    purge_forbidden_modules()
    loaded_before = forbidden_modules_loaded()
    if loaded_before:
        raise RuntimeError("forbidden modules were loaded before strategy execution")
    strategy = build_strategy(descriptor)
    simulator = EventSimulator(
        fill_model=_build_fill_model(execution),
        cost_model=LinearCostModel(fee_rate=execution.fee_rate),
        initial_cash=execution.initial_cash,
        risk_policy=risk_policy,
    )
    with block_forbidden_imports():
        result = simulator.run(strategy, events)
    loaded_after = forbidden_modules_loaded()
    if loaded_after:
        raise RuntimeError("strategy loaded forbidden modules")

    risk_fingerprint = stable_fingerprint(risk_document)
    events_fingerprint = stable_fingerprint([event.as_dict() for event in events])
    core = {
        "schema_version": 1,
        "status": "complete",
        "runtime_version": descriptor.runtime_version,
        "strategy_id": result.strategy_id,
        "strategy_source_sha256": descriptor.source_sha256,
        "descriptor_fingerprint": descriptor.descriptor_fingerprint,
        "strategy_config_fingerprint": descriptor.config_fingerprint,
        "execution_fingerprint": execution.fingerprint,
        "risk_fingerprint": risk_fingerprint,
        "events_fingerprint": events_fingerprint,
        "descriptor": {
            **descriptor.input_document(),
            "source_sha256": descriptor.source_sha256,
            "runtime_version": descriptor.runtime_version,
        },
        "execution": execution.as_dict(),
        "process_isolated": True,
        "credentials_present": any(is_sensitive_key(name) for name in os.environ),
        "network_or_order_modules_loaded": False,
        "events_processed": result.events_processed,
        "signals": result.signals,
        "intents": _serialize_rows(result.intents),
        "fills": _serialize_rows(result.fills),
        "misses": canonical_value(result.missed, allow_float=True),
        "rejections": canonical_value(result.rejected, allow_float=True),
        "costs": canonical_value(result.cost_components, allow_float=True),
        "equity": canonical_value(result.equity_curve, allow_float=True),
        "final_portfolio": canonical_value(result.final_snapshot, allow_float=True),
        "diagnostics": canonical_value(result.diagnostics, allow_float=True),
        "promotion_eligible": execution.promotion_eligible,
        "promotion_status": "blocked",
    }
    return {**core, "result_fingerprint": stable_fingerprint(core)}


def _set_output_limit(limit: int) -> None:
    resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))


def main(argv: list = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 3:
        return 1
    request_path, output_path, raw_limit = args
    try:
        output_limit = int(raw_limit)
        if output_limit <= 0:
            raise ValueError("output limit must be positive")
        _set_output_limit(output_limit)
        request = load_json_object(Path(request_path), label="worker request")
        result = execute_request(request)
        payload = json.dumps(result, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        if len(payload.encode("utf-8")) > output_limit:
            raise ValueError("worker result exceeds output limit")
        Path(output_path).write_text(payload + "\n", encoding="utf-8")
        return 0
    except BaseException as exc:
        sys.stderr.write(f"worker failed: {type(exc).__name__}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Credential-free subprocess worker for custom strategy replay."""

from __future__ import annotations

import json
import hashlib
import os
import resource
import sys
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Mapping, Sequence

from the_pass.data.contracts import (
    CanonicalEvent,
    canonical_json_bytes,
    canonical_value,
    stable_fingerprint,
)
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
        return BarFillModel(
            slippage_bps=config.slippage_bps,
            minimum_latency_ns=config.minimum_latency_ns,
            participation_rate=(
                config.participation_rate
                if config.schema_version == 2
                else Decimal("0.10")
            ),
        )
    if config.fill_model == "market_depth":
        return MarketDepthFillModel(
            minimum_latency_ns=config.minimum_latency_ns,
            participation_rate=config.participation_rate,
        )
    if config.fill_model == "limit_evidence":
        return LimitEvidenceFillModel(
            queue_haircut=config.queue_haircut,
            adverse_selection_haircut=config.adverse_selection_haircut,
            minimum_latency_ns=config.minimum_latency_ns,
            participation_rate=config.participation_rate,
        )
    if config.fill_model == "diagnostic_midpoint":
        return DiagnosticMidpointFillModel()
    raise ValueError("unsupported fill model")


def _serialize_rows(rows: Sequence[Any]) -> list:
    return [canonical_value(asdict(row), allow_float=True) for row in rows]


def _inspect_event_file(
    path: Path,
) -> tuple[int, str, set[str]]:
    digest = hashlib.sha256()
    digest.update(b"[")
    count = 0
    instruments: set[str] = set()
    previous_key = None
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            if not raw_line.strip():
                continue
            event = CanonicalEvent.from_dict(json.loads(raw_line))
            key = event.sort_key()
            if previous_key is not None and key < previous_key:
                raise ValueError("event file is not deterministically ordered")
            previous_key = key
            if count:
                digest.update(b",")
            digest.update(canonical_json_bytes(event.as_dict()))
            instruments.add(event.instrument_id)
            count += 1
    digest.update(b"]")
    if count == 0:
        raise ValueError("event file is empty")
    return count, digest.hexdigest(), instruments


def _iter_event_file(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            if raw_line.strip():
                yield CanonicalEvent.from_dict(json.loads(raw_line))


def execute_request(request: Mapping[str, Any]) -> Dict[str, Any]:
    request_v1 = {
        "schema_version",
        "workspace_root",
        "descriptor",
        "execution",
        "risk_policy",
        "events",
    }
    request_v2 = {
        "schema_version",
        "workspace_root",
        "descriptor",
        "execution",
        "risk_policy",
        "events_path",
        "events_count",
        "events_fingerprint",
        "checkpoint",
        "checkpoint_mode",
    }
    request_keys = frozenset(request)
    if request_keys not in {frozenset(request_v1), frozenset(request_v2)}:
        raise ValueError("worker request fields are invalid")
    if request["schema_version"] not in {1, 2} or isinstance(
        request["schema_version"], bool
    ):
        raise ValueError("worker request schema_version must be 1 or 2")
    if request["schema_version"] == 1 and set(request) != request_v1:
        raise ValueError("worker request v1 fields are invalid")
    if request["schema_version"] == 2 and set(request) != request_v2:
        raise ValueError("worker request v2 fields are invalid")
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
    if request["schema_version"] == 1:
        event_documents = request["events"]
        if not isinstance(event_documents, list) or not event_documents:
            raise ValueError("worker request requires a non-empty event list")
        events = sorted(
            (
                CanonicalEvent.from_dict(document)
                for document in event_documents
            ),
            key=CanonicalEvent.sort_key,
        )
        events_count = len(events)
        events_fingerprint = stable_fingerprint(
            [event.as_dict() for event in events]
        )
        instrument_ids = {event.instrument_id for event in events}
        event_iterable = events
    else:
        events_path = Path(str(request["events_path"])).resolve(strict=True)
        events_count, events_fingerprint, instrument_ids = (
            _inspect_event_file(events_path)
        )
        if (
            request["events_count"] != events_count
            or request["events_fingerprint"] != events_fingerprint
        ):
            raise ValueError(
                "worker event file count or fingerprint does not match request"
            )
        event_iterable = _iter_event_file(events_path)

    purge_forbidden_modules()
    loaded_before = forbidden_modules_loaded()
    if loaded_before:
        raise RuntimeError("forbidden modules were loaded before strategy execution")
    checkpoint = request.get("checkpoint")
    checkpoint_mode = bool(request.get("checkpoint_mode", False))
    risk_fingerprint = stable_fingerprint(risk_document)
    if checkpoint is not None and not isinstance(checkpoint, dict):
        raise ValueError("worker checkpoint must be an object or null")
    simulator_checkpoint = None
    strategy_state = None
    if checkpoint is not None:
        if checkpoint.get("schema_version") != 1:
            raise ValueError("worker checkpoint schema_version must be 1")
        checkpoint_core = {
            key: value
            for key, value in checkpoint.items()
            if key != "checkpoint_fingerprint"
        }
        if checkpoint.get("checkpoint_fingerprint") != stable_fingerprint(
            checkpoint_core
        ):
            raise ValueError("worker checkpoint fingerprint is invalid")
        expected_bindings = {
            "descriptor_fingerprint": descriptor.descriptor_fingerprint,
            "execution_fingerprint": execution.fingerprint,
            "risk_fingerprint": risk_fingerprint,
        }
        if any(
            checkpoint.get(key) != value
            for key, value in expected_bindings.items()
        ):
            raise ValueError(
                "worker checkpoint does not match strategy, execution, or risk inputs"
            )
        simulator_checkpoint = checkpoint.get("simulator")
        strategy_state = checkpoint.get("strategy_state")
        if not isinstance(simulator_checkpoint, dict):
            raise ValueError("worker checkpoint simulator state is invalid")
    strategy = build_strategy(
        descriptor,
        state=strategy_state,
        require_checkpoint=checkpoint_mode,
    )
    simulator = EventSimulator(
        fill_model=_build_fill_model(execution),
        cost_model=LinearCostModel(
            fee_rate=execution.fee_rate,
            impact_bps=execution.impact_bps,
        ),
        initial_cash=execution.initial_cash,
        risk_policy=risk_policy,
        equity_sampling_interval=execution.equity_sampling_interval,
    )
    with block_forbidden_imports():
        result = simulator.run_ordered(
            strategy,
            event_iterable,
            total_events=events_count,
            instrument_ids=instrument_ids,
            checkpoint=simulator_checkpoint,
            checkpoint_mode=checkpoint_mode,
        )
    loaded_after = forbidden_modules_loaded()
    if loaded_after:
        raise RuntimeError("strategy loaded forbidden modules")

    checkpoint_supported = callable(
        getattr(strategy, "export_state", None)
    ) and callable(getattr(strategy, "import_state", None))
    checkpoint_document = None
    if checkpoint_mode:
        with block_forbidden_imports():
            strategy_state = canonical_value(
                strategy.export_state(), allow_float=True
            )
        checkpoint_document = {
            "schema_version": 1,
            "descriptor_fingerprint": descriptor.descriptor_fingerprint,
            "execution_fingerprint": execution.fingerprint,
            "risk_fingerprint": risk_fingerprint,
            "strategy_state": strategy_state,
            "simulator": canonical_value(result.checkpoint),
        }
        checkpoint_document["checkpoint_fingerprint"] = stable_fingerprint(
            checkpoint_document
        )
    core = {
        "schema_version": 2,
        "status": "complete",
        "runtime_version": descriptor.runtime_version,
        "strategy_id": result.strategy_id,
        "strategy_source_sha256": descriptor.source_sha256,
        "descriptor_fingerprint": descriptor.descriptor_fingerprint,
        "strategy_config_fingerprint": descriptor.config_fingerprint,
        "execution_fingerprint": execution.fingerprint,
        "risk_fingerprint": risk_fingerprint,
        "events_fingerprint": events_fingerprint,
        "event_transport": (
            "inline_compatibility"
            if request["schema_version"] == 1
            else "canonical_jsonl"
        ),
        "checkpoint_supported": checkpoint_supported,
        "checkpoint": checkpoint_document,
        "descriptor": {
            **descriptor.input_document(),
            "source_sha256": descriptor.source_sha256,
            "runtime_version": descriptor.runtime_version,
        },
        "execution": execution.as_dict(),
        "process_isolated": True,
        "credentials_present": any(is_sensitive_key(name) for name in os.environ),
        "network_or_order_modules_loaded": bool(loaded_after),
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
        "promotion_eligible": execution.promotion_eligible
        and bool(result.diagnostics.get("promotion_eligible")),
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

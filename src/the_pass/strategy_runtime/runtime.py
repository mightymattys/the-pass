"""Public supervisor API for deterministic custom strategy subprocess runs."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

from the_pass.data.contracts import CanonicalEvent, stable_fingerprint
from the_pass.engine.contracts import Fill, RunnerResult, SimulatedIntent

from .config import (
    DescriptorInput,
    ExecutionConfig,
    ExecutionInput,
    StrategyDescriptor,
    load_execution_config,
    load_json_object,
    load_strategy_descriptor,
    parse_execution_config,
    parse_strategy_descriptor,
)
from .paths import PathLike


WORKER_ENV_ALLOWLIST = {"LANG", "LC_ALL", "PATH", "TMPDIR"}
DEFAULT_OUTPUT_LIMIT_BYTES = 5_000_000


class StrategyRuntimeError(RuntimeError):
    def __init__(self, message: str, *, metadata: Mapping[str, Any] = None) -> None:
        super().__init__(message)
        self.metadata = dict(metadata or {})


def _descriptor(value: DescriptorInput, workspace_root: PathLike) -> StrategyDescriptor:
    if isinstance(value, StrategyDescriptor):
        return parse_strategy_descriptor(value.input_document(), workspace_root=workspace_root)
    if isinstance(value, Path):
        return load_strategy_descriptor(value, workspace_root=workspace_root)
    if isinstance(value, Mapping):
        return parse_strategy_descriptor(value, workspace_root=workspace_root)
    raise TypeError("descriptor must be a path, mapping, or StrategyDescriptor")


def _execution(value: ExecutionInput) -> ExecutionConfig:
    if isinstance(value, ExecutionConfig):
        return parse_execution_config(value.input_document())
    if isinstance(value, Path):
        return load_execution_config(value)
    if isinstance(value, Mapping):
        return parse_execution_config(value)
    raise TypeError("execution must be a path, mapping, or ExecutionConfig")


def _worker_environment() -> Dict[str, str]:
    environment = {
        name: value for name, value in os.environ.items() if name in WORKER_ENV_ALLOWLIST
    }
    source_root = str(Path(__file__).resolve().parents[2])
    environment["PYTHONPATH"] = source_root
    return environment


def _failure_metadata(stderr_path: Path, stdout_path: Path, *, timed_out: bool) -> Dict[str, Any]:
    stderr = stderr_path.read_bytes() if stderr_path.is_file() else b""
    stdout = stdout_path.read_bytes() if stdout_path.is_file() else b""
    return {
        "timed_out": timed_out,
        "stderr_bytes": len(stderr),
        "stderr_sha256": hashlib.sha256(stderr).hexdigest(),
        "stdout_bytes": len(stdout),
        "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
    }


def _terminate(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    process.wait()


def run_strategy(
    events: Iterable[CanonicalEvent],
    *,
    descriptor: DescriptorInput,
    execution: ExecutionInput,
    workspace_root: PathLike,
    timeout_seconds: float = 60.0,
    output_limit_bytes: int = DEFAULT_OUTPUT_LIMIT_BYTES,
    risk_policy: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Run a ``CanonicalEvent`` sequence in a credential-free child process."""

    if isinstance(timeout_seconds, bool) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    if (
        not isinstance(output_limit_bytes, int)
        or isinstance(output_limit_bytes, bool)
        or output_limit_bytes <= 0
    ):
        raise ValueError("output_limit_bytes must be a positive integer")

    root = Path(workspace_root).expanduser().resolve(strict=True)
    parsed_descriptor = _descriptor(descriptor, root)
    parsed_execution = _execution(execution)
    rows = list(events)
    if not rows:
        raise ValueError("events must contain at least one CanonicalEvent")
    if any(not isinstance(event, CanonicalEvent) for event in rows):
        raise TypeError("events must contain only CanonicalEvent instances")
    rows.sort(key=CanonicalEvent.sort_key)
    events_fingerprint = stable_fingerprint([event.as_dict() for event in rows])

    request = {
        "schema_version": 1,
        "workspace_root": str(root),
        "descriptor": parsed_descriptor.input_document(),
        "execution": parsed_execution.input_document(),
        "risk_policy": dict(risk_policy or {"schema_version": 1, "policy_id": "diagnostic_allow_all_v1"}),
        "events": [event.as_dict() for event in rows],
    }
    with tempfile.TemporaryDirectory() as tmp:
        temp_root = Path(tmp)
        request_path = temp_root / "request.json"
        output_path = temp_root / "result.json"
        stdout_path = temp_root / "stdout.log"
        stderr_path = temp_root / "stderr.log"
        request_path.write_text(
            json.dumps(request, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
            encoding="utf-8",
        )
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "the_pass.strategy_runtime.worker",
                    str(request_path),
                    str(output_path),
                    str(output_limit_bytes),
                ],
                cwd=temp_root,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                env=_worker_environment(),
                start_new_session=True,
            )
            try:
                return_code = process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired as exc:
                _terminate(process)
                metadata = _failure_metadata(stderr_path, stdout_path, timed_out=True)
                raise StrategyRuntimeError("strategy worker timed out", metadata=metadata) from exc

        metadata = _failure_metadata(stderr_path, stdout_path, timed_out=False)
        if return_code != 0 or not output_path.is_file():
            metadata["return_code"] = return_code
            raise StrategyRuntimeError("strategy worker failed", metadata=metadata)
        if output_path.stat().st_size > output_limit_bytes:
            raise StrategyRuntimeError("strategy worker result exceeded output limit", metadata=metadata)
        try:
            result = load_json_object(output_path, label="strategy worker result")
        except ValueError as exc:
            raise StrategyRuntimeError("strategy worker returned malformed JSON", metadata=metadata) from exc

    fingerprint = result.pop("result_fingerprint", None)
    if not isinstance(fingerprint, str) or stable_fingerprint(result) != fingerprint:
        raise StrategyRuntimeError("strategy worker result fingerprint is invalid")
    result["result_fingerprint"] = fingerprint
    expected = {
        "descriptor_fingerprint": parsed_descriptor.descriptor_fingerprint,
        "strategy_source_sha256": parsed_descriptor.source_sha256,
        "execution_fingerprint": parsed_execution.fingerprint,
        "events_fingerprint": events_fingerprint,
        "risk_fingerprint": stable_fingerprint(request["risk_policy"]),
    }
    if any(result.get(key) != value for key, value in expected.items()):
        raise StrategyRuntimeError("strategy worker result does not match requested inputs")
    if result.get("credentials_present") or result.get("network_or_order_modules_loaded"):
        raise StrategyRuntimeError("strategy worker crossed its safety boundary")
    return result


def run_strategy_verified(
    events: Iterable[CanonicalEvent],
    *,
    descriptor: DescriptorInput,
    execution: ExecutionInput,
    workspace_root: PathLike,
    timeout_seconds: float = 60.0,
    output_limit_bytes: int = DEFAULT_OUTPUT_LIMIT_BYTES,
    risk_policy: Mapping[str, Any] | None = None,
) -> Dict[str, Any]:
    """Require two fresh workers to produce the same semantic result."""

    rows = list(events)
    first = run_strategy(
        rows,
        descriptor=descriptor,
        execution=execution,
        workspace_root=workspace_root,
        timeout_seconds=timeout_seconds,
        output_limit_bytes=output_limit_bytes,
        risk_policy=risk_policy,
    )
    second = run_strategy(
        rows,
        descriptor=descriptor,
        execution=execution,
        workspace_root=workspace_root,
        timeout_seconds=timeout_seconds,
        output_limit_bytes=output_limit_bytes,
        risk_policy=risk_policy,
    )
    if first != second:
        raise StrategyRuntimeError(
            "strategy result is not deterministic across fresh workers"
        )
    return {**first, "determinism_verified": True}


def runner_result_from_document(document: Mapping[str, Any]) -> RunnerResult:
    """Rehydrate canonical worker output for package and report generation."""

    intents = [
        SimulatedIntent(
            intent_id=str(row["intent_id"]),
            instrument_id=str(row["instrument_id"]),
            side=str(row["side"]),
            quantity=Decimal(str(row["quantity"])),
            decision_time_ns=int(row["decision_time_ns"]),
            intent_type=str(row["intent_type"]),
            limit_price=(
                Decimal(str(row["limit_price"]))
                if row.get("limit_price") is not None
                else None
            ),
        )
        for row in document["intents"]
    ]
    fills = [
        Fill(
            intent_id=str(row["intent_id"]),
            instrument_id=str(row["instrument_id"]),
            side=str(row["side"]),
            quantity=Decimal(str(row["quantity"])),
            price=Decimal(str(row["price"])),
            event_time_ns=int(row["event_time_ns"]),
            fee=Decimal(str(row["fee"])),
            spread_cost=Decimal(str(row["spread_cost"])),
            slippage_cost=Decimal(str(row["slippage_cost"])),
            evidence=str(row["evidence"]),
        )
        for row in document["fills"]
    ]
    return RunnerResult(
        strategy_id=str(document["strategy_id"]),
        events_processed=int(document["events_processed"]),
        signals=int(document["signals"]),
        intents=intents,
        fills=fills,
        rejected=list(document["rejections"]),
        missed=list(document["misses"]),
        equity_curve=list(document["equity"]),
        cost_components={
            key: Decimal(str(value)) for key, value in document["costs"].items()
        },
        final_snapshot=dict(document["final_portfolio"]),
        diagnostics=dict(document["diagnostics"]),
    )

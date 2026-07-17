"""Public supervisor API for deterministic custom strategy subprocess runs."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

from the_pass.data.contracts import (
    CanonicalEvent,
    canonical_json_bytes,
    stable_fingerprint,
)
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
RUNTIME_MODES = {"trusted_local", "hardened"}
HARDENED_REQUIREMENTS = {
    "network_enforcement": "denied",
    "filesystem_enforcement": "read_only_inputs_temp_output_only",
    "resource_enforcement": "os_enforced",
}


class StrategyRuntimeError(RuntimeError):
    def __init__(self, message: str, *, metadata: Mapping[str, Any] = None) -> None:
        super().__init__(message)
        self.metadata = dict(metadata or {})


def _event_file_metadata(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    digest.update(b"[")
    count = 0
    previous_key = None
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            if not raw_line.strip():
                continue
            event = CanonicalEvent.from_dict(json.loads(raw_line))
            key = event.sort_key()
            if previous_key is not None and key < previous_key:
                raise ValueError(
                    "canonical event file must be deterministically ordered"
                )
            previous_key = key
            if count:
                digest.update(b",")
            digest.update(canonical_json_bytes(event.as_dict()))
            count += 1
    digest.update(b"]")
    if count == 0:
        raise ValueError("canonical event file must not be empty")
    return count, digest.hexdigest()


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


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sandbox_launcher(path: Path | None) -> Path:
    if path is None:
        raise StrategyRuntimeError("hardened runtime requires an explicit sandbox launcher")
    launcher = path.expanduser().resolve(strict=True)
    mode = launcher.stat().st_mode
    if not stat.S_ISREG(mode) or launcher.is_symlink() or not os.access(launcher, os.X_OK):
        raise StrategyRuntimeError("sandbox launcher must be a regular executable file")
    return launcher


def _sandbox_policy(
    path: Path | None, *, launcher_sha256: str
) -> tuple[dict[str, Any], str]:
    if path is None:
        raise StrategyRuntimeError(
            "hardened runtime requires an explicit sandbox trust policy"
        )
    try:
        policy_path = path.expanduser().resolve(strict=True)
        document = load_json_object(policy_path, label="sandbox trust policy")
    except (OSError, ValueError) as exc:
        raise StrategyRuntimeError("sandbox trust policy is missing or invalid") from exc
    if set(document) != {"schema_version", "policy_id", "launchers"}:
        raise StrategyRuntimeError("sandbox trust policy has unexpected fields")
    if document["schema_version"] != 1:
        raise StrategyRuntimeError("sandbox trust policy schema_version must be 1")
    if not isinstance(document["policy_id"], str) or not document["policy_id"].strip():
        raise StrategyRuntimeError("sandbox trust policy requires policy_id")
    launchers = document["launchers"]
    if not isinstance(launchers, list):
        raise StrategyRuntimeError("sandbox trust policy launchers must be an array")
    matches = [
        row
        for row in launchers
        if isinstance(row, dict)
        and row.get("sha256") == launcher_sha256
        and row.get("requirements") == HARDENED_REQUIREMENTS
    ]
    if len(matches) != 1:
        raise StrategyRuntimeError(
            "sandbox launcher is not uniquely authorized by the trust policy"
        )
    return document, stable_fingerprint(document)


def _hardened_attestation(
    path: Path,
    *,
    launcher_sha256: str,
    request_fingerprint: str,
) -> Dict[str, Any]:
    try:
        document = load_json_object(path, label="sandbox attestation")
    except ValueError as exc:
        raise StrategyRuntimeError("hardened sandbox attestation is missing or invalid") from exc
    expected = {
        "schema_version": 1,
        "launcher_sha256": launcher_sha256,
        "request_fingerprint": request_fingerprint,
        **HARDENED_REQUIREMENTS,
    }
    if document != expected:
        raise StrategyRuntimeError("hardened sandbox attestation does not match the request")
    return document


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


def _run_sandbox_probe(
    *,
    launcher: Path,
    launcher_sha256: str,
    temp_root: Path,
    timeout_seconds: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    with tempfile.TemporaryDirectory() as forbidden_tmp:
        forbidden_root = Path(forbidden_tmp)
        forbidden_read = forbidden_root / "forbidden-read.txt"
        forbidden_write = forbidden_root / "forbidden-write.txt"
        forbidden_read.write_text("sandbox probe secret\n", encoding="utf-8")
        probe_output = temp_root / "sandbox-probe-result.json"
        probe_attestation = temp_root / "sandbox-probe-attestation.json"
        probe_request_path = temp_root / "sandbox-probe-request.json"
        stdout_path = temp_root / "sandbox-probe-stdout.log"
        stderr_path = temp_root / "sandbox-probe-stderr.log"
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            host, port = listener.getsockname()
            probe_argv = [
                sys.executable,
                "-m",
                "the_pass.strategy_runtime.sandbox_probe",
                str(probe_output),
                str(forbidden_read),
                str(forbidden_write),
                str(host),
                str(port),
            ]
            request_fingerprint = stable_fingerprint(
                {
                    "probe_contract": "the-pass/sandbox-probe/v1",
                    "launcher_sha256": launcher_sha256,
                    "requirements": HARDENED_REQUIREMENTS,
                }
            )
            request = {
                "schema_version": 1,
                "worker_argv": probe_argv,
                "working_directory": str(temp_root),
                "attestation_path": str(probe_attestation),
                "launcher_sha256": launcher_sha256,
                "request_fingerprint": request_fingerprint,
                "requirements": HARDENED_REQUIREMENTS,
            }
            probe_request_path.write_text(
                json.dumps(
                    request,
                    ensure_ascii=True,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
            with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
                process = subprocess.Popen(
                    [str(launcher), str(probe_request_path)],
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
                    raise StrategyRuntimeError("sandbox probe timed out") from exc
        if return_code != 0 or not probe_output.is_file():
            raise StrategyRuntimeError("sandbox probe failed")
        attestation = _hardened_attestation(
            probe_attestation,
            launcher_sha256=launcher_sha256,
            request_fingerprint=request_fingerprint,
        )
        try:
            probe = load_json_object(probe_output, label="sandbox probe result")
        except ValueError as exc:
            raise StrategyRuntimeError("sandbox probe returned malformed evidence") from exc
        expected = {
            "schema_version": 1,
            "forbidden_read_succeeded": False,
            "forbidden_write_succeeded": False,
            "network_connect_succeeded": False,
            "resource_limits_enforced": True,
        }
        if probe != expected:
            raise StrategyRuntimeError(
                "sandbox launcher failed active filesystem, network, or resource probes"
            )
        return probe, attestation


def run_strategy(
    events: Iterable[CanonicalEvent] | Path,
    *,
    descriptor: DescriptorInput,
    execution: ExecutionInput,
    workspace_root: PathLike,
    timeout_seconds: float = 60.0,
    output_limit_bytes: int = DEFAULT_OUTPUT_LIMIT_BYTES,
    risk_policy: Mapping[str, Any] | None = None,
    runtime_mode: str = "trusted_local",
    sandbox_launcher: Path | None = None,
    sandbox_policy: Path | None = None,
    checkpoint: Mapping[str, Any] | None = None,
    checkpoint_mode: bool = False,
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
    if runtime_mode not in RUNTIME_MODES:
        raise ValueError("runtime_mode must be trusted_local or hardened")
    if not isinstance(checkpoint_mode, bool):
        raise ValueError("checkpoint_mode must be boolean")
    if checkpoint is not None and not isinstance(checkpoint, Mapping):
        raise ValueError("checkpoint must be an object or null")
    launcher = _sandbox_launcher(sandbox_launcher) if runtime_mode == "hardened" else None
    if runtime_mode == "trusted_local" and (
        sandbox_launcher is not None or sandbox_policy is not None
    ):
        raise ValueError(
            "sandbox_launcher and sandbox_policy are valid only for hardened runtime mode"
        )
    launcher_sha256 = _file_sha256(launcher) if launcher is not None else None
    if launcher_sha256 is not None:
        policy_document, policy_fingerprint = _sandbox_policy(
            sandbox_policy, launcher_sha256=launcher_sha256
        )
    else:
        policy_document, policy_fingerprint = None, None

    root = Path(workspace_root).expanduser().resolve(strict=True)
    parsed_descriptor = _descriptor(descriptor, root)
    parsed_execution = _execution(execution)
    source_events_path: Path | None = None
    rows: list[CanonicalEvent] | None = None
    if isinstance(events, Path):
        source_events_path = events.expanduser().resolve(strict=True)
        events_count, events_fingerprint = _event_file_metadata(
            source_events_path
        )
    else:
        rows = list(events)
        if not rows:
            raise ValueError("events must contain at least one CanonicalEvent")
        if any(not isinstance(event, CanonicalEvent) for event in rows):
            raise TypeError("events must contain only CanonicalEvent instances")
        rows.sort(key=CanonicalEvent.sort_key)
        events_count = len(rows)
        events_fingerprint = stable_fingerprint(
            [event.as_dict() for event in rows]
        )

    risk_document = dict(
        risk_policy
        or {
            "schema_version": 1,
            "policy_id": "diagnostic_allow_all_v1",
        }
    )
    with tempfile.TemporaryDirectory() as tmp:
        temp_root = Path(tmp)
        events_path = temp_root / "canonical-events.jsonl"
        request_path = temp_root / "request.json"
        output_path = temp_root / "result.json"
        stdout_path = temp_root / "stdout.log"
        stderr_path = temp_root / "stderr.log"
        sandbox_request_path = temp_root / "sandbox-request.json"
        sandbox_attestation_path = temp_root / "sandbox-attestation.json"
        if source_events_path is not None:
            shutil.copyfile(source_events_path, events_path)
        else:
            with events_path.open("wb") as handle:
                for event in rows or []:
                    handle.write(
                        canonical_json_bytes(event.as_dict()) + b"\n"
                    )
                handle.flush()
                os.fsync(handle.fileno())
        request = {
            "schema_version": 2,
            "workspace_root": str(root),
            "descriptor": parsed_descriptor.input_document(),
            "execution": parsed_execution.input_document(),
            "risk_policy": risk_document,
            "events_path": str(events_path),
            "events_count": events_count,
            "events_fingerprint": events_fingerprint,
            "checkpoint": dict(checkpoint) if checkpoint is not None else None,
            "checkpoint_mode": checkpoint_mode,
        }
        if launcher is not None:
            sandbox_probe, sandbox_probe_attestation = _run_sandbox_probe(
                launcher=launcher,
                launcher_sha256=str(launcher_sha256),
                temp_root=temp_root,
                timeout_seconds=timeout_seconds,
            )
        else:
            sandbox_probe, sandbox_probe_attestation = None, None
        request_path.write_text(
            json.dumps(request, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
            encoding="utf-8",
        )
        worker_argv = [
            sys.executable,
            "-m",
            "the_pass.strategy_runtime.worker",
            str(request_path),
            str(output_path),
            str(output_limit_bytes),
        ]
        sandbox_request_fingerprint = None
        process_argv = worker_argv
        if launcher is not None:
            sandbox_request_fingerprint = stable_fingerprint(
                {
                    "strategy_request": {
                        key: value
                        for key, value in request.items()
                        if key not in {"workspace_root", "events_path"}
                    },
                    "worker_contract": "the-pass/strategy-worker/v1",
                    "output_limit_bytes": output_limit_bytes,
                    "launcher_sha256": launcher_sha256,
                    "requirements": HARDENED_REQUIREMENTS,
                }
            )
            sandbox_request = {
                "schema_version": 1,
                "worker_argv": worker_argv,
                "working_directory": str(temp_root),
                "attestation_path": str(sandbox_attestation_path),
                "launcher_sha256": launcher_sha256,
                "request_fingerprint": sandbox_request_fingerprint,
                "requirements": HARDENED_REQUIREMENTS,
            }
            sandbox_request_path.write_text(
                json.dumps(sandbox_request, ensure_ascii=True, separators=(",", ":"), sort_keys=True),
                encoding="utf-8",
            )
            process_argv = [str(launcher), str(sandbox_request_path)]
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            process = subprocess.Popen(
                process_argv,
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

        if runtime_mode == "hardened":
            sandbox_attestation = _hardened_attestation(
                sandbox_attestation_path,
                launcher_sha256=str(launcher_sha256),
                request_fingerprint=str(sandbox_request_fingerprint),
            )
        else:
            sandbox_attestation = None

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
    isolation = {
        "mode": runtime_mode,
        "process_separation": True,
        "credentials_stripped": True,
        "import_filter": "known_module_denylist",
        "network_enforcement": "none",
        "filesystem_enforcement": "none",
        "resource_enforcement": "process_timeout_and_output_limit",
        "launcher_sha256": None,
        "attestation_fingerprint": None,
        "policy_id": None,
        "policy_fingerprint": None,
        "probe_fingerprint": None,
        "probe_attestation_fingerprint": None,
    }
    if sandbox_attestation is not None:
        isolation.update(
            {
                **HARDENED_REQUIREMENTS,
                "launcher_sha256": launcher_sha256,
                "attestation_fingerprint": stable_fingerprint(sandbox_attestation),
                "policy_id": policy_document["policy_id"],
                "policy_fingerprint": policy_fingerprint,
                "probe_fingerprint": stable_fingerprint(sandbox_probe),
                "probe_attestation_fingerprint": stable_fingerprint(
                    sandbox_probe_attestation
                ),
            }
        )
    result["isolation"] = isolation
    result["runtime_promotion_eligible"] = (
        runtime_mode == "hardened"
        and sandbox_attestation is not None
        and sandbox_probe is not None
        and policy_document is not None
        and result.get("promotion_eligible") is True
    )
    result["result_fingerprint"] = stable_fingerprint(
        {key: value for key, value in result.items() if key != "result_fingerprint"}
    )
    return result


def run_strategy_verified(
    events: Iterable[CanonicalEvent] | Path,
    *,
    descriptor: DescriptorInput,
    execution: ExecutionInput,
    workspace_root: PathLike,
    timeout_seconds: float = 60.0,
    output_limit_bytes: int = DEFAULT_OUTPUT_LIMIT_BYTES,
    risk_policy: Mapping[str, Any] | None = None,
    runtime_mode: str = "trusted_local",
    sandbox_launcher: Path | None = None,
    sandbox_policy: Path | None = None,
    checkpoint: Mapping[str, Any] | None = None,
    checkpoint_mode: bool = False,
) -> Dict[str, Any]:
    """Require two fresh workers to produce the same semantic result."""

    rows: Iterable[CanonicalEvent] | Path = (
        events if isinstance(events, Path) else list(events)
    )
    first = run_strategy(
        rows,
        descriptor=descriptor,
        execution=execution,
        workspace_root=workspace_root,
        timeout_seconds=timeout_seconds,
        output_limit_bytes=output_limit_bytes,
        risk_policy=risk_policy,
        runtime_mode=runtime_mode,
        sandbox_launcher=sandbox_launcher,
        sandbox_policy=sandbox_policy,
        checkpoint=checkpoint,
        checkpoint_mode=checkpoint_mode,
    )
    second = run_strategy(
        rows,
        descriptor=descriptor,
        execution=execution,
        workspace_root=workspace_root,
        timeout_seconds=timeout_seconds,
        output_limit_bytes=output_limit_bytes,
        risk_policy=risk_policy,
        runtime_mode=runtime_mode,
        sandbox_launcher=sandbox_launcher,
        sandbox_policy=sandbox_policy,
        checkpoint=checkpoint,
        checkpoint_mode=checkpoint_mode,
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
            impact_cost=Decimal(str(row.get("impact_cost", "0"))),
            latency_ns=int(row.get("latency_ns", 0)),
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
        checkpoint=(
            dict(document["checkpoint"])
            if isinstance(document.get("checkpoint"), Mapping)
            else None
        ),
    )

"""Resumable, replay-based paper observation for trusted local strategies."""

from __future__ import annotations

import json
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from the_pass.data.contracts import CanonicalEvent, canonical_value, stable_fingerprint
from the_pass.strategy_runtime import (
    load_execution_config,
    load_strategy_descriptor,
    run_strategy_verified,
)

from .runtime import ObservationPolicy, validate_observation


class PaperObservationError(RuntimeError):
    """Raised when an observation cannot safely continue."""


def _json_bytes(document: object) -> bytes:
    return (
        json.dumps(
            canonical_value(document, allow_float=True),
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _write_atomic(path: Path, document: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_json_bytes(document))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


@contextmanager
def _exclusive_lock(root: Path) -> Iterator[None]:
    root.mkdir(parents=True, exist_ok=True)
    lock = root / "LOCK"
    try:
        descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise PaperObservationError("paper observation is already locked") from exc
    os.close(descriptor)
    try:
        yield
    finally:
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def _read_json(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise PaperObservationError(f"paper artifact must be an object: {path}")
    return document


def _append_invocation(root: Path, core: dict[str, Any]) -> dict[str, Any]:
    path = root / "invocations.jsonl"
    previous_hash = "0" * 64
    if path.is_file():
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
        if lines:
            previous = json.loads(lines[-1])
            previous_hash = str(previous["entry_hash"])
    entry_core = {**core, "previous_hash": previous_hash}
    entry = {**entry_core, "entry_hash": stable_fingerprint(entry_core)}
    with path.open("ab") as handle:
        handle.write(
            json.dumps(canonical_value(entry), separators=(",", ":"), sort_keys=True).encode("utf-8")
            + b"\n"
        )
        handle.flush()
        os.fsync(handle.fileno())
    return entry


def _load_batches(root: Path, state: Mapping[str, Any]) -> list[CanonicalEvent]:
    events: list[CanonicalEvent] = []
    for row in state["batches"]:
        path = root / str(row["path"])
        raw = path.read_bytes()
        if stable_fingerprint(raw.decode("utf-8")) != row["file_fingerprint"]:
            raise PaperObservationError(f"paper batch fingerprint mismatch: {path.name}")
        for line in raw.decode("utf-8").splitlines():
            if line:
                events.append(CanonicalEvent.from_dict(json.loads(line)))
    ingest_ids = [event.ingest_id for event in events]
    if len(ingest_ids) != len(set(ingest_ids)):
        raise PaperObservationError("paper batches contain overlapping ingest_id values")
    return sorted(events, key=CanonicalEvent.sort_key)


def _freeze(
    root: Path,
    state: dict[str, Any],
    *,
    batch_id: str,
    breaches: list[dict[str, Any]],
    observation_time_ns: int,
) -> dict[str, Any]:
    state = {
        **state,
        "status": "frozen",
        "breaches": breaches,
        "last_observation_time_ns": observation_time_ns,
    }
    _write_atomic(root / "observation.json", state)
    _append_invocation(
        root,
        {
            "schema_version": 1,
            "sequence": len(state.get("runs", [])) + 1,
            "batch_id": batch_id,
            "status": "frozen",
            "observation_time_ns": observation_time_ns,
            "state_fingerprint": stable_fingerprint(state),
            "breaches": breaches,
        },
    )
    return state


def observe_strategy(
    events: Iterable[CanonicalEvent],
    *,
    batch_id: str,
    descriptor_path: Path,
    execution_path: Path,
    risk_policy: Mapping[str, Any],
    observation_policy: ObservationPolicy,
    observation_time_ns: int,
    observation_dir: Path,
    workspace_root: Path,
    timeout_seconds: float = 60.0,
) -> dict[str, Any]:
    """Commit one immutable batch and rebuild cumulative paper evidence."""

    if re.fullmatch(r"[A-Za-z0-9_-]+", batch_id) is None:
        raise ValueError("batch_id must contain only letters, numbers, hyphen, or underscore")
    rows = sorted(list(events), key=CanonicalEvent.sort_key)
    if not rows or any(not isinstance(event, CanonicalEvent) for event in rows):
        raise ValueError("paper batch requires CanonicalEvent values")
    root = observation_dir.resolve()
    descriptor = load_strategy_descriptor(descriptor_path, workspace_root=workspace_root)
    execution = load_execution_config(execution_path)
    config_core = {
        "strategy_id": descriptor.strategy_id,
        "strategy_source_sha256": descriptor.source_sha256,
        "descriptor_fingerprint": descriptor.descriptor_fingerprint,
        "execution_fingerprint": execution.fingerprint,
        "risk_fingerprint": stable_fingerprint(risk_policy),
        "observation_policy": observation_policy.__dict__,
        "runtime_version": descriptor.runtime_version,
    }
    config_hash = stable_fingerprint(config_core)
    batch_payload = "\n".join(
        json.dumps(event.as_dict(), separators=(",", ":"), sort_keys=True) for event in rows
    ) + "\n"
    batch_file_fingerprint = stable_fingerprint(batch_payload)
    batch_events_fingerprint = stable_fingerprint([event.as_dict() for event in rows])

    with _exclusive_lock(root):
        state_path = root / "observation.json"
        if state_path.is_file():
            state = _read_json(state_path)
            if state.get("status") == "frozen":
                raise PaperObservationError("paper observation is frozen")
            if state.get("config_hash") != config_hash:
                return _freeze(
                    root,
                    state,
                    batch_id=batch_id,
                    breaches=[
                        {
                            "code": "config_drift",
                            "severity": "critical",
                            "blocks_runtime": True,
                        }
                    ],
                    observation_time_ns=observation_time_ns,
                )
        else:
            state = {
                "schema_version": 1,
                "observation_id": f"paper-{config_hash[:16]}",
                "strategy_id": descriptor.strategy_id,
                "status": "observing",
                "config": config_core,
                "config_hash": config_hash,
                "batches": [],
                "runs": [],
                "signals": 0,
                "fills": 0,
                "elapsed_time_verified": False,
                "paper_gate_eligible": False,
                "breaches": [],
            }

        existing = next(
            (row for row in state["batches"] if row["batch_id"] == batch_id), None
        )
        if existing is not None:
            if existing["events_fingerprint"] != batch_events_fingerprint:
                return _freeze(
                    root,
                    state,
                    batch_id=batch_id,
                    breaches=[
                        {
                            "code": "batch_conflict",
                            "severity": "critical",
                            "blocks_runtime": True,
                        }
                    ],
                    observation_time_ns=observation_time_ns,
                )
            return {**state, "invocation_status": "duplicate"}

        batch_relative = Path("batches") / f"{batch_id}.jsonl"
        batch_path = root / batch_relative
        batch_path.parent.mkdir(parents=True, exist_ok=True)
        if batch_path.exists():
            raise PaperObservationError("untracked paper batch file already exists")
        with batch_path.open("xb") as handle:
            handle.write(batch_payload.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        state["batches"].append(
            {
                "batch_id": batch_id,
                "path": batch_relative.as_posix(),
                "events_fingerprint": batch_events_fingerprint,
                "file_fingerprint": batch_file_fingerprint,
                "event_count": len(rows),
            }
        )
        try:
            cumulative = _load_batches(root, state)
        except PaperObservationError as exc:
            return _freeze(
                root,
                state,
                batch_id=batch_id,
                breaches=[
                    {
                        "code": "batch_overlap_or_tamper",
                        "severity": "critical",
                        "blocks_runtime": True,
                        "reason": str(exc),
                    }
                ],
                observation_time_ns=observation_time_ns,
            )
        breaches = validate_observation(
            cumulative,
            observation_time_ns=observation_time_ns,
            policy=observation_policy,
        )
        if breaches:
            return _freeze(
                root,
                state,
                batch_id=batch_id,
                breaches=breaches,
                observation_time_ns=observation_time_ns,
            )
        try:
            result = run_strategy_verified(
                cumulative,
                descriptor=descriptor,
                execution=execution,
                risk_policy=risk_policy,
                workspace_root=workspace_root,
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            return _freeze(
                root,
                state,
                batch_id=batch_id,
                breaches=[
                    {
                        "code": "strategy_worker_failure",
                        "severity": "critical",
                        "blocks_runtime": True,
                        "error_type": type(exc).__name__,
                    }
                ],
                observation_time_ns=observation_time_ns,
            )
        previous_result_path = root / "current-result.json"
        if previous_result_path.is_file():
            previous = _read_json(previous_result_path)
            for field in ("intents", "fills"):
                if result[field][: len(previous[field])] != previous[field]:
                    return _freeze(
                        root,
                        state,
                        batch_id=batch_id,
                        breaches=[
                            {
                                "code": "historical_prefix_divergence",
                                "severity": "critical",
                                "blocks_runtime": True,
                                "field": field,
                            }
                        ],
                        observation_time_ns=observation_time_ns,
                    )
        risk_codes = {
            "max_position_units",
            "max_notional",
            "missing_reference_price",
            "missing_daily_equity",
            "max_daily_loss",
        }
        risk_breaches = [
            row for row in result["rejections"] if row.get("reason") in risk_codes
        ]
        if risk_breaches:
            return _freeze(
                root,
                state,
                batch_id=batch_id,
                breaches=[
                    {
                        "code": "risk_limit",
                        "severity": "critical",
                        "blocks_runtime": True,
                        "rejections": risk_breaches,
                    }
                ],
                observation_time_ns=observation_time_ns,
            )
        sequence = len(state["runs"]) + 1
        run_relative = Path("runs") / f"{sequence:06d}.json"
        run_path = root / run_relative
        if run_path.exists():
            raise PaperObservationError("paper run sequence already exists")
        _write_atomic(run_path, result)
        _write_atomic(previous_result_path, result)
        state = {
            **state,
            "status": "observing",
            "runs": [
                *state["runs"],
                {
                    "sequence": sequence,
                    "path": run_relative.as_posix(),
                    "result_fingerprint": result["result_fingerprint"],
                },
            ],
            "signals": result["signals"],
            "fills": len(result["fills"]),
            "events": len(cumulative),
            "first_event_time_ns": cumulative[0].event_time_ns,
            "last_event_time_ns": cumulative[-1].event_time_ns,
            "last_observation_time_ns": observation_time_ns,
            "elapsed_time_verified": False,
            "paper_gate_eligible": False,
            "breaches": [],
        }
        _write_atomic(state_path, state)
        invocation = _append_invocation(
            root,
            {
                "schema_version": 1,
                "sequence": sequence,
                "batch_id": batch_id,
                "status": "observing",
                "observation_time_ns": observation_time_ns,
                "state_fingerprint": stable_fingerprint(state),
                "result_fingerprint": result["result_fingerprint"],
                "breaches": [],
            },
        )
        return {**state, "invocation_status": "complete", "invocation": invocation}

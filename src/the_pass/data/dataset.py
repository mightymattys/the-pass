"""Deterministic, resumable composition of immutable adapter ingest chunks."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from the_pass.adapters.base import FetchRequest, ReadOnlyAdapter

from .contracts import CanonicalEvent, canonical_json_bytes, stable_fingerprint
from .ingest import OfflineIngestService, validate_ingest_bundle
from .quality import QualityPolicy, build_quality_report


PLAN_PATH = Path("dataset-plan.json")
EVENTS_PATH = Path("canonical-events.jsonl")
QUALITY_PATH = Path("quality-report.json")
MANIFEST_PATH = Path("data-manifest.json")
RECEIPT_PATH = Path("dataset-receipt.json")


@dataclass(frozen=True)
class DatasetBuildResult:
    output_dir: Path
    events_path: Path
    quality_path: Path
    manifest_path: Path
    receipt_path: Path
    committed_path: Path
    event_count: int
    dataset_fingerprint: str
    promotion_impact: str
    resumed_chunks: int
    fetched_chunks: int


def request_document(request: FetchRequest) -> dict[str, Any]:
    return {
        "kind": request.kind,
        "instrument_id": request.instrument_id,
        "start_ns": request.start_ns,
        "end_ns": request.end_ns,
        "limit": request.limit,
        "parameters": dict(request.parameters) if request.parameters is not None else None,
    }


def request_from_document(document: Mapping[str, Any]) -> FetchRequest:
    allowed = {"kind", "instrument_id", "start_ns", "end_ns", "limit", "parameters"}
    if set(document) != allowed:
        raise ValueError("dataset chunk request fields are invalid")
    if not isinstance(document["kind"], str) or not document["kind"]:
        raise ValueError("dataset chunk kind must be a non-empty string")
    for field in ("start_ns", "end_ns", "limit"):
        value = document[field]
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            raise ValueError(f"dataset chunk {field} must be a non-negative integer or null")
    parameters = document["parameters"]
    if parameters is not None and not isinstance(parameters, dict):
        raise ValueError("dataset chunk parameters must be an object or null")
    return FetchRequest(
        kind=document["kind"],
        instrument_id=document["instrument_id"],
        start_ns=document["start_ns"],
        end_ns=document["end_ns"],
        limit=document["limit"],
        parameters=parameters,
    )


def build_dataset_plan(
    *,
    plan_id: str,
    provider: str,
    kind: str,
    instrument_id: str,
    start_ns: int,
    end_ns: int,
    chunk_ns: int,
    created_at: str,
    limit: int | None = None,
    parameters: Mapping[str, Any] | None = None,
    expected_interval_ns: int | None = None,
    cross_check_required: bool = False,
) -> dict[str, Any]:
    if not all(isinstance(value, str) and value.strip() for value in (plan_id, provider, kind, instrument_id, created_at)):
        raise ValueError("dataset plan string fields must be non-empty")
    for field, value in (("start_ns", start_ns), ("end_ns", end_ns), ("chunk_ns", chunk_ns)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{field} must be a non-negative integer")
    if start_ns >= end_ns or chunk_ns <= 0:
        raise ValueError("dataset plan requires start_ns < end_ns and positive chunk_ns")
    if expected_interval_ns is not None and (
        isinstance(expected_interval_ns, bool) or expected_interval_ns <= 0
    ):
        raise ValueError("expected_interval_ns must be positive when provided")
    requests = []
    cursor = start_ns
    index = 0
    while cursor < end_ns:
        chunk_end = min(cursor + chunk_ns, end_ns)
        request = FetchRequest(
            kind=kind,
            instrument_id=instrument_id,
            start_ns=cursor,
            end_ns=chunk_end,
            limit=limit,
            parameters=dict(parameters or {}),
        )
        requests.append(
            {
                "chunk_id": f"chunk-{index:06d}",
                "request": request_document(request),
                "request_fingerprint": stable_fingerprint(request_document(request)),
            }
        )
        cursor = chunk_end
        index += 1
    core = {
        "schema_version": 1,
        "id": plan_id,
        "created_at": created_at,
        "provider": provider,
        "kind": kind,
        "instrument_id": instrument_id,
        "requested_interval": {"start_ns": start_ns, "end_ns": end_ns},
        "chunk_ns": chunk_ns,
        "expected_interval_ns": expected_interval_ns,
        "cross_check_required": bool(cross_check_required),
        "requests": requests,
    }
    return {**core, "plan_fingerprint": stable_fingerprint(core)}


def validate_dataset_plan(document: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "schema_version",
        "id",
        "created_at",
        "provider",
        "kind",
        "instrument_id",
        "requested_interval",
        "chunk_ns",
        "expected_interval_ns",
        "cross_check_required",
        "requests",
        "plan_fingerprint",
    }
    if set(document) != required or document.get("schema_version") != 1:
        raise ValueError("dataset plan fields or schema_version are invalid")
    if not all(
        isinstance(document.get(field), str) and document[field].strip()
        for field in ("id", "created_at", "provider", "kind", "instrument_id")
    ):
        raise ValueError("dataset plan string fields must be non-empty")
    if (
        isinstance(document.get("chunk_ns"), bool)
        or not isinstance(document.get("chunk_ns"), int)
        or document["chunk_ns"] <= 0
    ):
        raise ValueError("dataset plan chunk_ns must be positive")
    expected_interval = document.get("expected_interval_ns")
    if expected_interval is not None and (
        isinstance(expected_interval, bool)
        or not isinstance(expected_interval, int)
        or expected_interval <= 0
    ):
        raise ValueError("dataset plan expected_interval_ns must be positive or null")
    if not isinstance(document.get("cross_check_required"), bool):
        raise ValueError("dataset plan cross_check_required must be boolean")
    core = {key: value for key, value in document.items() if key != "plan_fingerprint"}
    if document["plan_fingerprint"] != stable_fingerprint(core):
        raise ValueError("dataset plan fingerprint is invalid")
    interval = document["requested_interval"]
    if not isinstance(interval, dict) or set(interval) != {"start_ns", "end_ns"}:
        raise ValueError("dataset requested_interval is invalid")
    if any(
        isinstance(interval.get(field), bool)
        or not isinstance(interval.get(field), int)
        or interval[field] < 0
        for field in ("start_ns", "end_ns")
    ) or interval["start_ns"] >= interval["end_ns"]:
        raise ValueError("dataset requested_interval must satisfy start_ns < end_ns")
    requests = document["requests"]
    if not isinstance(requests, list) or not requests:
        raise ValueError("dataset plan requires chunk requests")
    cursor = interval["start_ns"]
    seen = set()
    for index, item in enumerate(requests):
        if not isinstance(item, dict) or set(item) != {
            "chunk_id",
            "request",
            "request_fingerprint",
        }:
            raise ValueError("dataset chunk descriptor is invalid")
        if item["chunk_id"] in seen or item["chunk_id"] != f"chunk-{index:06d}":
            raise ValueError("dataset chunk IDs must be unique and ordered")
        seen.add(item["chunk_id"])
        request = request_from_document(item["request"])
        if item["request_fingerprint"] != stable_fingerprint(item["request"]):
            raise ValueError("dataset chunk request fingerprint is invalid")
        if request.start_ns != cursor or request.end_ns is None or request.end_ns <= cursor:
            raise ValueError("dataset chunks must be contiguous and non-overlapping")
        if request.instrument_id != document["instrument_id"] or request.kind != document["kind"]:
            raise ValueError("dataset chunk does not match plan instrument and kind")
        cursor = request.end_ns
    if cursor != interval["end_ns"]:
        raise ValueError("dataset chunks do not cover the exact requested interval")
    return dict(document)


@contextmanager
def _exclusive_dataset_lock(output_dir: Path) -> Iterator[None]:
    output_dir = output_dir.resolve()
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    lock_path = output_dir.parent / f".{output_dir.name}.lock"
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt

            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX)
        acquired = True
        yield
    finally:
        if acquired:
            if os.name == "nt":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(canonical_json_bytes(value, allow_float=True) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, path)
    except Exception:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass
        raise


def _load_chunk(
    chunk_dir: Path, expected_request: Mapping[str, Any]
) -> tuple[list[CanonicalEvent], dict[str, Any], str]:
    try:
        bundle = validate_ingest_bundle(
            chunk_dir,
            expected_request=expected_request,
        )
    except ValueError as exc:
        raise ValueError(f"dataset chunk {chunk_dir.name} is invalid: {exc}") from exc
    return list(bundle.events), dict(bundle.receipt), bundle.bundle_fingerprint


def _read_canonical_events(path: Path) -> list[CanonicalEvent]:
    try:
        return [
            CanonicalEvent.from_dict(json.loads(line))
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (json.JSONDecodeError, KeyError, OSError, TypeError, ValueError) as exc:
        raise ValueError("committed dataset canonical events are invalid") from exc


def _validate_committed_dataset(
    root: Path, plan: Mapping[str, Any]
) -> tuple[dict[str, Any], list[CanonicalEvent]]:
    required = (
        root / PLAN_PATH,
        root / EVENTS_PATH,
        root / QUALITY_PATH,
        root / MANIFEST_PATH,
        root / RECEIPT_PATH,
        root / "COMMITTED",
    )
    if not all(path.is_file() for path in required):
        raise ValueError("committed dataset is missing required artifacts")
    if _read_json(root / PLAN_PATH) != plan:
        raise ValueError("committed dataset plan differs from requested plan")
    receipt = _read_json(root / RECEIPT_PATH)
    receipt_core = {
        key: value for key, value in receipt.items() if key != "commit_fingerprint"
    }
    expected_commit = stable_fingerprint(receipt_core)
    if (
        receipt.get("commit_fingerprint") != expected_commit
        or (root / "COMMITTED").read_text(encoding="ascii").strip()
        != expected_commit
    ):
        raise ValueError("committed dataset fingerprint is invalid")
    if receipt.get("plan_fingerprint") != plan["plan_fingerprint"]:
        raise ValueError("committed dataset plan fingerprint does not match")
    events = _read_canonical_events(root / EVENTS_PATH)
    if not events or stable_fingerprint(
        [event.as_dict() for event in events]
    ) != receipt.get("dataset_fingerprint"):
        raise ValueError("committed dataset event fingerprint does not match")
    quality = _read_json(root / QUALITY_PATH)
    manifest = _read_json(root / MANIFEST_PATH)
    if stable_fingerprint(quality) != receipt.get("quality_fingerprint"):
        raise ValueError("committed dataset quality fingerprint does not match")
    if stable_fingerprint(manifest) != receipt.get("manifest_fingerprint"):
        raise ValueError("committed dataset manifest fingerprint does not match")
    if receipt.get("event_count") != len(events):
        raise ValueError("committed dataset event count does not match")
    chunk_rows = receipt.get("chunks")
    if not isinstance(chunk_rows, list) or len(chunk_rows) != len(plan["requests"]):
        raise ValueError("committed dataset chunk receipt count does not match")
    receipt_version = receipt.get("schema_version")
    if receipt_version not in {1, 2} or isinstance(receipt_version, bool):
        raise ValueError("committed dataset receipt schema version is invalid")
    for descriptor, row in zip(plan["requests"], chunk_rows):
        if not isinstance(row, dict) or row.get("chunk_id") != descriptor["chunk_id"]:
            raise ValueError("committed dataset chunk order does not match")
        _, chunk_receipt, bundle_fingerprint = _load_chunk(
            root / "chunks" / descriptor["chunk_id"], descriptor["request"]
        )
        expected = {
            "chunk_id": descriptor["chunk_id"],
            "request_fingerprint": descriptor["request_fingerprint"],
            "receipt_fingerprint": chunk_receipt["receipt_fingerprint"],
            "canonical_fingerprint": chunk_receipt["canonical_fingerprint"],
            "event_count": chunk_receipt["event_count"],
            "cross_check": chunk_receipt["cross_check"],
        }
        if receipt_version == 2:
            expected["bundle_fingerprint"] = bundle_fingerprint
        if row != expected:
            raise ValueError("committed dataset chunk evidence does not match")
    return receipt, events


def _build_dataset_locked(
    adapter: ReadOnlyAdapter,
    plan: Mapping[str, Any],
    output_dir: Path,
    *,
    cross_check_references: Mapping[str, Any] | None = None,
    clock_ns: Callable[[], int] | None = None,
) -> DatasetBuildResult:
    plan = validate_dataset_plan(plan)
    if plan["provider"] not in {adapter.adapter_id, adapter.adapter_id.split("-")[0]}:
        aliases = {
            "binance": "binance-spot-public",
            "polymarket": "polymarket-public",
            "futures": "databento-compatible-futures",
        }
        if aliases.get(plan["provider"]) != adapter.adapter_id:
            raise ValueError("dataset plan provider does not match adapter")
    root = output_dir.resolve()
    committed = root / "COMMITTED"
    if committed.exists():
        receipt, _ = _validate_committed_dataset(root, plan)
        return DatasetBuildResult(
            root,
            root / EVENTS_PATH,
            root / QUALITY_PATH,
            root / MANIFEST_PATH,
            root / RECEIPT_PATH,
            committed,
            int(receipt["event_count"]),
            str(receipt["dataset_fingerprint"]),
            str(receipt["promotion_impact"]),
            len(plan["requests"]),
            0,
        )
    root.mkdir(parents=True, exist_ok=True)
    if (root / PLAN_PATH).exists():
        if _read_json(root / PLAN_PATH) != plan:
            raise ValueError("partial dataset plan differs from requested plan")
    else:
        _write_atomic(root / PLAN_PATH, plan)

    service = OfflineIngestService(**({} if clock_ns is None else {"clock_ns": clock_ns}))
    references = dict(cross_check_references or {})
    all_events: list[CanonicalEvent] = []
    chunk_rows = []
    resumed = 0
    fetched = 0
    for descriptor in plan["requests"]:
        chunk_id = descriptor["chunk_id"]
        chunk_dir = root / "chunks" / chunk_id
        request = request_from_document(descriptor["request"])
        if chunk_dir.exists():
            events, receipt, bundle_fingerprint = _load_chunk(
                chunk_dir, descriptor["request"]
            )
            resumed += 1
        else:
            result = service.ingest(
                adapter,
                request,
                chunk_dir,
                cross_check_reference=references.get(chunk_id),
            )
            events, receipt, bundle_fingerprint = _load_chunk(
                chunk_dir, descriptor["request"]
            )
            if result.canonical_fingerprint != receipt["canonical_fingerprint"]:
                raise ValueError(f"dataset chunk result mismatch: {chunk_id}")
            fetched += 1
        all_events.extend(events)
        chunk_rows.append(
            {
                "chunk_id": chunk_id,
                "request_fingerprint": descriptor["request_fingerprint"],
                "receipt_fingerprint": receipt["receipt_fingerprint"],
                "canonical_fingerprint": receipt["canonical_fingerprint"],
                "event_count": receipt["event_count"],
                "cross_check": receipt["cross_check"],
                "bundle_fingerprint": bundle_fingerprint,
            }
        )

    identities: dict[tuple[Any, ...], CanonicalEvent] = {}
    for event in all_events:
        identity = (
            event.source,
            event.venue,
            event.instrument_id,
            event.event_type.value,
            event.event_time_ns,
            event.sequence,
            event.ingest_id,
        )
        previous = identities.get(identity)
        if previous is not None and previous.as_dict() != event.as_dict():
            raise ValueError("conflicting duplicate canonical event blocks dataset publication")
        identities[identity] = event
    ordered = sorted(identities.values(), key=CanonicalEvent.sort_key)
    if not ordered:
        raise ValueError("dataset build produced no canonical events")
    dataset_fingerprint = stable_fingerprint([event.as_dict() for event in ordered])
    interval = plan["requested_interval"]
    expected_interval = plan["expected_interval_ns"]
    requested_quality_end = (
        interval["end_ns"] - expected_interval if expected_interval is not None else None
    )
    quality = build_quality_report(
        plan["id"],
        ordered,
        policy=QualityPolicy(
            expected_interval_ns=expected_interval,
            requested_start_ns=interval["start_ns"],
            requested_end_ns=requested_quality_end,
        ),
        created_at=plan["created_at"],
    )
    cross_checks_pass = all(
        row["cross_check"].get("status") == "pass" for row in chunk_rows
    )
    cross_check_blocked = bool(plan["cross_check_required"] and not cross_checks_pass)
    promotion_impact = (
        "blocked"
        if quality["promotion_impact"] == "blocked" or cross_check_blocked
        else quality["promotion_impact"]
    )
    manifest = adapter.build_manifest(
        ordered,
        raw_path=Path("chunks"),
        quality_report=quality,
    )
    manifest["id"] = plan["id"]
    manifest["created_at"] = plan["created_at"]
    manifest["source"]["raw_path"] = "chunks"
    manifest["source"]["normalized_path"] = EVENTS_PATH.as_posix()
    manifest["quality"]["cross_source_checks"] = [
        f"{row['chunk_id']}:{row['cross_check'].get('status', 'invalid')}"
        for row in chunk_rows
    ]
    if cross_check_blocked:
        manifest["limitations"].append("required cross-source checks are incomplete")
    receipt_core = {
        "schema_version": 2,
        "id": f"receipt-{plan['id']}",
        "created_at": plan["created_at"],
        "plan_fingerprint": plan["plan_fingerprint"],
        "dataset_fingerprint": dataset_fingerprint,
        "quality_fingerprint": stable_fingerprint(quality),
        "manifest_fingerprint": stable_fingerprint(manifest),
        "event_count": len(ordered),
        "chunks": chunk_rows,
        "cross_check_required": plan["cross_check_required"],
        "cross_check_status": "pass" if cross_checks_pass else "incomplete",
        "promotion_impact": promotion_impact,
    }
    receipt = {**receipt_core, "commit_fingerprint": stable_fingerprint(receipt_core)}
    # JSONL is kept as the runtime interchange format rather than a JSON array.
    events_payload = b"".join(canonical_json_bytes(event.as_dict()) + b"\n" for event in ordered)
    descriptor, name = tempfile.mkstemp(prefix=".canonical-events.", suffix=".tmp", dir=str(root))
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(events_payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, root / EVENTS_PATH)
    except Exception:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass
        raise
    _write_atomic(root / QUALITY_PATH, quality)
    _write_atomic(root / MANIFEST_PATH, manifest)
    _write_atomic(root / RECEIPT_PATH, receipt)
    descriptor = os.open(committed, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="ascii") as handle:
        handle.write(receipt["commit_fingerprint"] + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return DatasetBuildResult(
        root,
        root / EVENTS_PATH,
        root / QUALITY_PATH,
        root / MANIFEST_PATH,
        root / RECEIPT_PATH,
        committed,
        len(ordered),
        dataset_fingerprint,
        promotion_impact,
        resumed,
        fetched,
    )


def build_dataset(
    adapter: ReadOnlyAdapter,
    plan: Mapping[str, Any],
    output_dir: Path,
    *,
    cross_check_references: Mapping[str, Any] | None = None,
    clock_ns: Callable[[], int] | None = None,
) -> DatasetBuildResult:
    """Build or verify one immutable dataset under an output-scoped lock."""

    with _exclusive_dataset_lock(output_dir):
        return _build_dataset_locked(
            adapter,
            plan,
            output_dir,
            cross_check_references=cross_check_references,
            clock_ns=clock_ns,
        )

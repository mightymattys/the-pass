"""Provider-neutral offline ingest into immutable evidence bundles."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
import inspect
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from the_pass.adapters.base import FetchRequest, ReadOnlyAdapter

from .contracts import CanonicalEvent, canonical_json_bytes, canonical_value, stable_fingerprint
from .quality import QualityPolicy, build_quality_report


RAW_PATH = Path("raw") / "response.json"
CANONICAL_PATH = Path("canonical-events.jsonl")
QUALITY_PATH = Path("quality-report.json")
MANIFEST_PATH = Path("data-manifest.json")
REQUEST_PATH = Path("request.json")
RECEIPT_PATH = Path("ingest-receipt.json")
COMMITTED_PATH = Path("COMMITTED")


class BundleExistsError(FileExistsError):
    """Raised when an ingest would replace an existing output path."""


@dataclass(frozen=True)
class IngestResult:
    output_dir: Path
    raw_path: Path
    canonical_path: Path
    quality_path: Path
    manifest_path: Path
    request_path: Path
    receipt_path: Path
    committed_path: Path
    raw_fingerprint: str
    canonical_fingerprint: str
    event_count: int
    quality_report: dict[str, object]
    data_manifest: dict[str, object]


@dataclass(frozen=True)
class ValidatedIngestBundle:
    output_dir: Path
    request: dict[str, object]
    raw: object
    events: tuple[CanonicalEvent, ...]
    quality_report: dict[str, object]
    data_manifest: dict[str, object]
    receipt: dict[str, object]
    bundle_fingerprint: str


class OfflineIngestService:
    """Run one bounded adapter fetch and atomically publish its evidence bundle."""

    def __init__(self, *, clock_ns: Callable[[], int] = time.time_ns) -> None:
        self._clock_ns = clock_ns

    def ingest(
        self,
        adapter: ReadOnlyAdapter,
        request: FetchRequest,
        output_dir: Path,
        *,
        quality_policy: QualityPolicy | None = None,
        dataset_id: str | None = None,
        cross_check_reference: object | None = None,
    ) -> IngestResult:
        target = Path(os.path.abspath(output_dir))
        if os.path.lexists(target):
            raise BundleExistsError(f"ingest bundle already exists: {target}")

        raw = adapter.fetch_raw(request)
        receive_time_ns = self._clock_ns()
        if isinstance(receive_time_ns, bool) or not isinstance(receive_time_ns, int) or receive_time_ns < 0:
            raise ValueError("clock_ns must return non-negative UTC nanoseconds")

        normalized = list(adapter.normalize(raw, request, receive_time_ns=receive_time_ns))
        if not normalized:
            raise ValueError("adapter normalized no canonical events")
        if any(not isinstance(event, CanonicalEvent) for event in normalized):
            raise TypeError("adapter normalize must return CanonicalEvent values")

        request_document = _request_document(request)
        request_fingerprint = stable_fingerprint(request_document)
        raw_fingerprint = stable_fingerprint(raw)
        ordered = sorted(normalized, key=CanonicalEvent.sort_key)
        canonical_fingerprint = stable_fingerprint([event.as_dict() for event in ordered])
        resolved_dataset_id = dataset_id or f"manifest-{canonical_fingerprint[:16]}"
        policy = quality_policy or default_chunk_quality_policy(request)
        created_at = _rfc3339(max(receive_time_ns, *(event.receive_time_ns for event in normalized)))
        quality_report = build_quality_report(
            resolved_dataset_id,
            normalized,
            policy=policy,
            created_at=created_at,
        )

        data_manifest = adapter.build_manifest(
            ordered,
            raw_path=RAW_PATH,
            quality_report=quality_report,
        )
        _bind_manifest_paths(data_manifest)
        if data_manifest.get("id") != resolved_dataset_id:
            raise ValueError("adapter manifest id does not match the quality dataset_id")
        cross_check = (
            adapter.cross_check(ordered, cross_check_reference)
            if cross_check_reference is not None
            else {"status": "not_performed", "reason": "no reference supplied"}
        )
        cost_snapshot = (
            adapter.cost_snapshot(request.instrument_id, observed_at_ns=receive_time_ns)
            if request.instrument_id
            else {"status": "not_applicable", "reason": "request has no instrument_id"}
        )
        receipt_core = {
            "schema_version": 1,
            "adapter_id": adapter.adapter_id,
            "adapter_code_fingerprint": stable_fingerprint(
                inspect.getsource(type(adapter))
            ),
            "capabilities": asdict(adapter.capabilities),
            "request_fingerprint": request_fingerprint,
            "raw_fingerprint": raw_fingerprint,
            "canonical_fingerprint": canonical_fingerprint,
            "quality_report_fingerprint": stable_fingerprint(quality_report),
            "data_manifest_fingerprint": stable_fingerprint(data_manifest),
            "event_count": len(ordered),
            "cross_check": cross_check,
            "cost_snapshot": cost_snapshot,
            "promotion_mode": adapter.capabilities.maximum_promotion_mode,
            "transport_evidence": canonical_value(
                getattr(getattr(adapter, "client", None), "evidence", []),
                allow_float=True,
            ),
        }
        ingest_receipt = {
            **receipt_core,
            "receipt_fingerprint": stable_fingerprint(receipt_core),
        }

        target.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(
            tempfile.mkdtemp(
                prefix=f".{target.name}.staging-",
                dir=str(target.parent),
            )
        )
        try:
            _write_bytes(staging / RAW_PATH, canonical_json_bytes(raw, allow_float=True) + b"\n")
            _write_bytes(
                staging / REQUEST_PATH,
                canonical_json_bytes(request_document, allow_float=True) + b"\n",
            )
            _write_bytes(
                staging / CANONICAL_PATH,
                b"".join(canonical_json_bytes(event.as_dict()) + b"\n" for event in ordered),
            )
            _write_bytes(
                staging / QUALITY_PATH,
                canonical_json_bytes(quality_report, allow_float=True) + b"\n",
            )
            _write_bytes(
                staging / MANIFEST_PATH,
                canonical_json_bytes(data_manifest, allow_float=True) + b"\n",
            )
            _write_bytes(
                staging / RECEIPT_PATH,
                canonical_json_bytes(ingest_receipt, allow_float=True) + b"\n",
            )
            _write_bytes(
                staging / COMMITTED_PATH,
                (ingest_receipt["receipt_fingerprint"] + "\n").encode("ascii"),
            )
            validate_ingest_bundle(staging, expected_request=request_document)
            if os.path.lexists(target):
                raise BundleExistsError(f"ingest bundle already exists: {target}")
            try:
                os.rename(staging, target)
            except OSError as exc:
                if os.path.lexists(target):
                    raise BundleExistsError(f"ingest bundle already exists: {target}") from exc
                raise
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

        return IngestResult(
            output_dir=target,
            raw_path=target / RAW_PATH,
            canonical_path=target / CANONICAL_PATH,
            quality_path=target / QUALITY_PATH,
            manifest_path=target / MANIFEST_PATH,
            request_path=target / REQUEST_PATH,
            receipt_path=target / RECEIPT_PATH,
            committed_path=target / COMMITTED_PATH,
            raw_fingerprint=raw_fingerprint,
            canonical_fingerprint=canonical_fingerprint,
            event_count=len(ordered),
            quality_report=quality_report,
            data_manifest=data_manifest,
        )


def ingest_bundle(
    adapter: ReadOnlyAdapter,
    request: FetchRequest,
    output_dir: Path,
    *,
    quality_policy: QualityPolicy | None = None,
    dataset_id: str | None = None,
    cross_check_reference: object | None = None,
    clock_ns: Callable[[], int] = time.time_ns,
) -> IngestResult:
    """Convenience entry point for a single offline ingest."""

    return OfflineIngestService(clock_ns=clock_ns).ingest(
        adapter,
        request,
        output_dir,
        quality_policy=quality_policy,
        dataset_id=dataset_id,
        cross_check_reference=cross_check_reference,
    )


def default_chunk_quality_policy(
    request: FetchRequest, *, expected_interval_ns: int | None = None
) -> QualityPolicy:
    """Build half-open chunk coverage policy for point-labeled bar events."""

    corrected_end = request.end_ns
    if expected_interval_ns is not None and corrected_end is not None:
        candidate = corrected_end - expected_interval_ns
        corrected_end = (
            candidate
            if request.start_ns is None or candidate > request.start_ns
            else None
        )
    return QualityPolicy(
        expected_interval_ns=expected_interval_ns,
        requested_start_ns=request.start_ns,
        requested_end_ns=corrected_end,
    )


def _request_document(request: FetchRequest) -> dict[str, object]:
    return {
        "kind": request.kind,
        "instrument_id": request.instrument_id,
        "start_ns": request.start_ns,
        "end_ns": request.end_ns,
        "limit": request.limit,
        "parameters": canonical_value(request.parameters, allow_float=True) if request.parameters is not None else None,
    }


def _bind_manifest_paths(manifest: dict[str, object]) -> None:
    source = manifest.get("source")
    if not isinstance(source, dict):
        raise TypeError("adapter manifest source must be a dictionary")
    source["raw_path"] = RAW_PATH.as_posix()
    source["normalized_path"] = CANONICAL_PATH.as_posix()


def _read_json(path: Path, *, label: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeError) as exc:
        raise ValueError(f"ingest bundle {label} is invalid") from exc


def _artifact_fingerprint(receipt: Mapping[str, object]) -> str:
    return stable_fingerprint(
        {
            "request_fingerprint": receipt["request_fingerprint"],
            "raw_fingerprint": receipt["raw_fingerprint"],
            "canonical_fingerprint": receipt["canonical_fingerprint"],
            "quality_report_fingerprint": receipt["quality_report_fingerprint"],
            "data_manifest_fingerprint": receipt["data_manifest_fingerprint"],
            "receipt_fingerprint": receipt["receipt_fingerprint"],
            "event_count": receipt["event_count"],
        }
    )


def validate_ingest_bundle(
    output_dir: Path,
    *,
    expected_request: Mapping[str, object] | None = None,
) -> ValidatedIngestBundle:
    """Recompute every immutable ingest artifact and return trusted bundle contents."""

    root = Path(os.path.abspath(output_dir))
    paths = {
        "request": root / REQUEST_PATH,
        "raw response": root / RAW_PATH,
        "canonical events": root / CANONICAL_PATH,
        "quality report": root / QUALITY_PATH,
        "data manifest": root / MANIFEST_PATH,
        "receipt": root / RECEIPT_PATH,
        "commit marker": root / COMMITTED_PATH,
    }
    for label, path in paths.items():
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"ingest bundle {label} is missing or not a regular file")

    request = _read_json(paths["request"], label="request")
    raw = _read_json(paths["raw response"], label="raw response")
    quality = _read_json(paths["quality report"], label="quality report")
    manifest = _read_json(paths["data manifest"], label="data manifest")
    receipt = _read_json(paths["receipt"], label="receipt")
    if not all(isinstance(value, dict) for value in (request, quality, manifest, receipt)):
        raise ValueError("ingest bundle structured artifacts must be JSON objects")
    if expected_request is not None and request != dict(expected_request):
        raise ValueError("ingest bundle request changed")

    from the_pass.validator import validate_artifact

    for label, artifact_type in (
        ("quality report", "quality_report"),
        ("data manifest", "data_manifest"),
    ):
        validation = validate_artifact(paths[label], artifact_type=artifact_type)
        if not validation.ok:
            details = "; ".join(
                f"{issue.path}: {issue.message}" for issue in validation.issues
            )
            raise ValueError(f"ingest bundle {label} does not validate: {details}")

    try:
        events = tuple(
            CanonicalEvent.from_dict(json.loads(line))
            for line in paths["canonical events"].read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    except (json.JSONDecodeError, KeyError, OSError, TypeError, UnicodeError, ValueError) as exc:
        raise ValueError("ingest bundle canonical events are invalid") from exc
    if not events:
        raise ValueError("ingest bundle canonical events are empty")

    receipt_core = {
        key: value for key, value in receipt.items() if key != "receipt_fingerprint"
    }
    expected_receipt = stable_fingerprint(receipt_core)
    if receipt.get("receipt_fingerprint") != expected_receipt:
        raise ValueError("ingest bundle receipt fingerprint is invalid")
    try:
        marker = paths["commit marker"].read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise ValueError("ingest bundle commit marker is invalid") from exc
    if marker != expected_receipt:
        raise ValueError("ingest bundle commit fingerprint is invalid")

    checks = (
        ("request", stable_fingerprint(request), receipt.get("request_fingerprint")),
        ("raw response", stable_fingerprint(raw), receipt.get("raw_fingerprint")),
        (
            "canonical events",
            stable_fingerprint([event.as_dict() for event in events]),
            receipt.get("canonical_fingerprint"),
        ),
        ("quality report", stable_fingerprint(quality), receipt.get("quality_report_fingerprint")),
        ("data manifest", stable_fingerprint(manifest), receipt.get("data_manifest_fingerprint")),
    )
    for label, observed, expected in checks:
        if observed != expected:
            raise ValueError(f"ingest bundle {label} fingerprint is invalid")
    if receipt.get("event_count") != len(events):
        raise ValueError("ingest bundle event count is invalid")
    canonical_fingerprint = checks[2][1]
    if quality.get("dataset_fingerprint") != canonical_fingerprint:
        raise ValueError("ingest bundle quality report dataset fingerprint is invalid")
    if quality.get("summary", {}).get("events") != len(events):
        raise ValueError("ingest bundle quality report event count is invalid")
    if manifest.get("quality", {}).get("row_count") != len(events):
        raise ValueError("ingest bundle data manifest row count is invalid")
    if manifest.get("fingerprint", {}).get("value") != canonical_fingerprint:
        raise ValueError("ingest bundle data manifest canonical fingerprint is invalid")

    source = manifest.get("source")
    if not isinstance(source, dict):
        raise ValueError("ingest bundle data manifest source is invalid")
    if source.get("raw_path") != RAW_PATH.as_posix():
        raise ValueError("ingest bundle data manifest raw_path is invalid")
    if source.get("normalized_path") != CANONICAL_PATH.as_posix():
        raise ValueError("ingest bundle data manifest normalized_path is invalid")
    if manifest.get("id") != quality.get("dataset_id"):
        raise ValueError("ingest bundle quality report and manifest dataset IDs differ")

    return ValidatedIngestBundle(
        output_dir=root,
        request=request,
        raw=raw,
        events=events,
        quality_report=quality,
        data_manifest=manifest,
        receipt=receipt,
        bundle_fingerprint=_artifact_fingerprint(receipt),
    )


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _rfc3339(value_ns: int) -> str:
    value = datetime.fromtimestamp(value_ns / 1_000_000_000, tz=timezone.utc)
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")

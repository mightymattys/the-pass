"""Provider-neutral offline ingest into immutable evidence bundles."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import inspect
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

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
        policy = quality_policy or QualityPolicy(
            requested_start_ns=request.start_ns,
            requested_end_ns=request.end_ns,
        )
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


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def _rfc3339(value_ns: int) -> str:
    value = datetime.fromtimestamp(value_ns / 1_000_000_000, tz=timezone.utc)
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")

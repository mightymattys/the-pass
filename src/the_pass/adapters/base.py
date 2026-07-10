"""Shared protocol and retry-limited public HTTP transport."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Iterable, Mapping, Protocol, runtime_checkable

from the_pass.data.contracts import CanonicalEvent, Instrument, stable_fingerprint
from the_pass.data.raw_archive import RawResponseArchive


@dataclass(frozen=True)
class AdapterCapabilities:
    event_types: tuple[str, ...]
    historical_read: bool
    live_read: bool
    authentication: str
    replay: bool
    timestamp_quality: str
    license_mode: str
    maximum_promotion_mode: str


@dataclass(frozen=True)
class FetchRequest:
    kind: str
    instrument_id: str | None = None
    start_ns: int | None = None
    end_ns: int | None = None
    limit: int | None = None
    parameters: Mapping[str, Any] | None = None


class HttpResponse(Protocol):
    status_code: int

    def json(self) -> Any: ...

    def raise_for_status(self) -> None: ...


class HttpTransport(Protocol):
    def get(self, url: str, *, params: Mapping[str, Any] | None = None, timeout: float = 15.0) -> HttpResponse: ...


class PublicHttpClient:
    """GET-only client. Retries are restricted to idempotent public reads."""

    def __init__(
        self,
        transport: HttpTransport | None = None,
        *,
        attempts: int = 3,
        timeout: float = 15.0,
        archive: RawResponseArchive | None = None,
        provider: str = "public-http",
        min_interval_seconds: float = 0.05,
    ) -> None:
        if attempts < 1:
            raise ValueError("attempts must be positive")
        if transport is None:
            try:
                import httpx
            except ImportError as exc:
                raise RuntimeError("public HTTP adapters require the 'data' extra") from exc
            transport = httpx.Client(headers={"User-Agent": "the-pass-read-only/0.3"})
        self._transport = transport
        self._attempts = attempts
        self._timeout = timeout
        self._archive = archive
        self._provider = provider
        self._min_interval_seconds = max(0.0, min_interval_seconds)
        self._last_request_at = 0.0
        self.evidence: list[dict[str, Any]] = []

    def get_json(self, url: str, *, params: Mapping[str, Any] | None = None) -> Any:
        last_error: Exception | None = None
        for attempt in range(self._attempts):
            try:
                elapsed = time.monotonic() - self._last_request_at
                if elapsed < self._min_interval_seconds:
                    time.sleep(self._min_interval_seconds - elapsed)
                self._last_request_at = time.monotonic()
                response = self._transport.get(url, params=params, timeout=self._timeout)
                if response.status_code == 429 or response.status_code >= 500:
                    raise RuntimeError(f"temporary provider status {response.status_code}")
                response.raise_for_status()
                payload = response.json()
                received_at_ns = time.time_ns()
                archive_path = None
                fingerprint = stable_fingerprint(payload)
                if self._archive is not None:
                    archive_path, fingerprint = self._archive.store(
                        provider=self._provider,
                        stream="rest",
                        received_at_ns=received_at_ns,
                        payload=payload,
                    )
                self.evidence.append(
                    {
                        "url": url,
                        "status_code": response.status_code,
                        "received_at_ns": received_at_ns,
                        "response_fingerprint": fingerprint,
                        "archive_path": str(archive_path) if archive_path else None,
                        "attempt": attempt + 1,
                    }
                )
                return payload
            except Exception as exc:
                last_error = exc
                self.evidence.append(
                    {
                        "url": url,
                        "received_at_ns": time.time_ns(),
                        "error_type": type(exc).__name__,
                        "attempt": attempt + 1,
                    }
                )
                if attempt + 1 == self._attempts:
                    break
                time.sleep(0.1 * (2**attempt))
        raise RuntimeError(f"public read failed after {self._attempts} attempt(s): {last_error}") from last_error


@dataclass
class StreamEvidence:
    connections: int = 0
    reconnects: int = 0
    messages: int = 0
    archived_messages: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)


async def reconnecting_json_stream(
    *,
    url: str,
    provider: str,
    stream: str,
    archive: RawResponseArchive,
    subscription: Mapping[str, Any] | None = None,
    max_reconnects: int = 5,
    evidence: StreamEvidence | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Receive and archive a public stream with bounded reconnect evidence."""

    try:
        import websockets
    except ImportError as exc:
        raise RuntimeError("market streams require the 'data' extra") from exc
    evidence = evidence or StreamEvidence()
    while True:
        try:
            evidence.connections += 1
            async with websockets.connect(url, ping_interval=20, ping_timeout=20, close_timeout=10) as websocket:
                if subscription is not None:
                    import json

                    await websocket.send(json.dumps(subscription, separators=(",", ":")))
                async for message in websocket:
                    import json

                    received_at_ns = time.time_ns()
                    payload = json.loads(message)
                    archive.store(provider=provider, stream=stream, received_at_ns=received_at_ns, payload=payload)
                    evidence.messages += 1
                    evidence.archived_messages += 1
                    yield payload
        except Exception as exc:
            evidence.errors.append({"error_type": type(exc).__name__, "observed_at_ns": time.time_ns()})
            if evidence.reconnects >= max_reconnects:
                raise RuntimeError(f"stream reconnect budget exhausted for {provider}:{stream}") from exc
            evidence.reconnects += 1
            await _sleep(min(2**evidence.reconnects, 30))


async def _sleep(seconds: float) -> None:
    import asyncio

    await asyncio.sleep(seconds)


@runtime_checkable
class ReadOnlyAdapter(Protocol):
    adapter_id: str
    capabilities: AdapterCapabilities

    def discover_instruments(self, request: FetchRequest | None = None) -> list[Instrument]: ...

    def fetch_raw(self, request: FetchRequest) -> Any: ...

    def normalize(self, raw: Any, request: FetchRequest, *, receive_time_ns: int) -> list[CanonicalEvent]: ...

    def cross_check(self, primary: Iterable[CanonicalEvent], reference: Any) -> dict[str, Any]: ...

    def build_manifest(self, events: Iterable[CanonicalEvent], *, raw_path: Path, quality_report: dict[str, Any]) -> dict[str, Any]: ...

    def cost_snapshot(self, instrument_id: str, *, observed_at_ns: int) -> dict[str, Any]: ...


def manifest_for_events(
    adapter_id: str,
    events: Iterable[CanonicalEvent],
    *,
    raw_path: Path,
    quality_report: dict[str, Any],
    endpoint: str,
    license_note: str,
) -> dict[str, Any]:
    rows = sorted(events, key=CanonicalEvent.sort_key)
    if not rows:
        raise ValueError("manifest requires at least one event")
    if quality_report.get("promotion_impact") == "blocked":
        limitations = ["quality report blocks promotion"]
    else:
        limitations = []
    fingerprint = stable_fingerprint([event.as_dict() for event in rows])

    def rfc3339(value_ns: int) -> str:
        value = datetime.fromtimestamp(value_ns / 1_000_000_000, tz=timezone.utc)
        return value.isoformat(timespec="microseconds").replace("+00:00", "Z")

    return {
        "schema_version": 2,
        "id": f"manifest-{fingerprint[:16]}",
        "dataset_name": f"{adapter_id}-{rows[0].instrument_id}",
        "created_at": rfc3339(max(event.receive_time_ns for event in rows)),
        "owner": "the-pass",
        "source": {
            "provider": adapter_id,
            "venue": rows[0].venue,
            "endpoint_or_file": endpoint,
            "license_note": license_note,
            "raw_path": str(raw_path),
            "normalized_path": "",
        },
        "coverage": {
            "instruments": sorted({event.instrument_id for event in rows}),
            "start_time": rfc3339(rows[0].event_time_ns),
            "end_time": rfc3339(rows[-1].event_time_ns),
            "timezone": "UTC",
            "event_time_field": "event_time_ns",
            "receive_time_field": "receive_time_ns",
        },
        "schema": {
            "fields": sorted(rows[0].as_dict()),
            "primary_keys": ["instrument_id", "event_type", "event_time_ns", "sequence", "ingest_id"],
            "known_null_fields": ["sequence"],
        },
        "quality": {
            "row_count": len(rows),
            "missing_intervals": [item for check in quality_report["checks"] if check["code"] == "missing_intervals" for item in check["affected"]],
            "duplicate_policy": "duplicates block promotion",
            "sequence_gap_policy": "sequence gaps block promotion where provider sequences exist",
            "cross_source_checks": [],
        },
        "fingerprint": {"method": "sha256", "value": fingerprint},
        "limitations": limitations,
    }

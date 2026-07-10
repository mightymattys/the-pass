"""Databento-compatible futures archive adapter with no bundled licensed data."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from the_pass.data.contracts import CanonicalEvent, EventType, Instrument

from .base import AdapterCapabilities, FetchRequest, manifest_for_events


class DatabentoCompatibleFuturesAdapter:
    adapter_id = "databento-compatible-futures"

    def __init__(self, archive_root: Path, *, licensed_archive: bool = False) -> None:
        self.archive_root = archive_root.resolve()
        self.licensed_archive = licensed_archive
        self.capabilities = AdapterCapabilities(
            event_types=("instrument_definition", "bar", "trade", "quote", "settlement", "open_interest"),
            historical_read=True,
            live_read=False,
            authentication="local archive process only; never serialized",
            replay=True,
            timestamp_quality="provider event and receive timestamps where archive supplies both",
            license_mode="user-supplied licensed archive" if licensed_archive else "public synthetic fixture",
            maximum_promotion_mode="research" if licensed_archive else "diagnostic",
        )

    def _safe_path(self, relative: str) -> Path:
        candidate = (self.archive_root / relative).resolve()
        try:
            candidate.relative_to(self.archive_root)
        except ValueError as exc:
            raise ValueError("archive path escapes configured root") from exc
        return candidate

    def discover_instruments(self, request: FetchRequest | None = None) -> list[Instrument]:
        relative = str((request.parameters or {}).get("definitions", "instrument_definitions.json")) if request else "instrument_definitions.json"
        rows = json.loads(self._safe_path(relative).read_text(encoding="utf-8"))
        return [
            Instrument(
                instrument_id=row["instrument_id"],
                symbol=row["symbol"],
                venue=row["venue"],
                asset_class="futures",
                tick_size=Decimal(row["tick_size"]),
                lot_size=Decimal(row.get("lot_size", "1")),
                multiplier=Decimal(row["multiplier"]),
                quote_currency=row["quote_currency"],
                contract_type="future",
                expiry=row["expiry"],
                margin_mode=row.get("margin_mode"),
            )
            for row in rows
        ]

    def fetch_raw(self, request: FetchRequest) -> Any:
        relative = str((request.parameters or {}).get("fixture", "events.json"))
        return json.loads(self._safe_path(relative).read_text(encoding="utf-8"))

    def normalize(self, raw: Any, request: FetchRequest, *, receive_time_ns: int) -> list[CanonicalEvent]:
        events = []
        for index, row in enumerate(raw):
            event_type = EventType(row["event_type"])
            payload = {
                key: Decimal(value) if key in {"price", "size", "open", "high", "low", "close", "volume", "settlement_price"} else value
                for key, value in row["payload"].items()
            }
            events.append(
                CanonicalEvent.from_raw(
                    raw=row,
                    source=self.adapter_id,
                    venue=row["venue"],
                    asset_class="futures",
                    instrument_id=row["instrument_id"],
                    event_type=event_type,
                    event_time_ns=int(row["event_time_ns"]),
                    receive_time_ns=int(row.get("receive_time_ns", receive_time_ns)),
                    ingest_id=f"futures-fixture-{row['instrument_id']}-{index}",
                    sequence=row.get("sequence"),
                    payload=payload,
                )
            )
        return events

    def cross_check(self, primary: Iterable[CanonicalEvent], reference: Any) -> dict[str, Any]:
        rows = list(primary)
        contracts = {event.instrument_id for event in rows}
        back_adjusted_execution = any(bool(event.payload.get("back_adjusted")) for event in rows if event.event_type == EventType.TRADE)
        return {
            "status": "fail" if back_adjusted_execution else "pass",
            "contracts": sorted(contracts),
            "raw_contracts_preserved": bool(contracts),
            "execution_uses_concrete_contract": not back_adjusted_execution,
            "reference": reference,
        }

    def build_manifest(self, events: Iterable[CanonicalEvent], *, raw_path: Path, quality_report: dict[str, Any]) -> dict[str, Any]:
        manifest = manifest_for_events(
            self.adapter_id,
            events,
            raw_path=raw_path,
            quality_report=quality_report,
            endpoint="user-supplied Databento-compatible archive",
            license_note="archive owner must confirm license and redistribution restrictions",
        )
        if not self.licensed_archive:
            manifest["limitations"].append("synthetic fixture is diagnostic-only")
        return manifest

    def cost_snapshot(self, instrument_id: str, *, observed_at_ns: int) -> dict[str, Any]:
        return {
            "instrument_id": instrument_id,
            "observed_at_ns": observed_at_ns,
            "status": "requires_provider_schedule",
            "components": ["exchange_fee", "commission", "spread", "slippage", "roll"],
        }

    def settlement_snapshot(self, instrument_id: str, *, observed_at_ns: int) -> dict[str, Any]:
        return {
            "instrument_id": instrument_id,
            "observed_at_ns": observed_at_ns,
            "status": "requires_archive_settlement_record",
        }


def build_volume_rolled_series(events: Iterable[CanonicalEvent]) -> list[dict[str, Any]]:
    """Build a deterministic back-adjusted signal series with concrete execution contracts."""

    bars = [event for event in events if event.event_type == EventType.BAR]
    grouped: dict[int, list[CanonicalEvent]] = {}
    for event in bars:
        grouped.setdefault(event.event_time_ns, []).append(event)
    if not grouped:
        raise ValueError("volume roll requires bar events")

    selected: list[CanonicalEvent] = []
    for timestamp in sorted(grouped):
        candidates = grouped[timestamp]
        winner = max(
            candidates,
            key=lambda event: (Decimal(str(event.payload.get("volume", "0"))), event.instrument_id),
        )
        selected.append(winner)

    adjustment = Decimal(0)
    previous: CanonicalEvent | None = None
    rows = []
    for event in selected:
        close = Decimal(str(event.payload["close"]))
        rolled = previous is not None and previous.instrument_id != event.instrument_id
        if rolled:
            previous_close = Decimal(str(previous.payload["close"]))
            adjustment += previous_close - close
        rows.append(
            {
                "event_time_ns": event.event_time_ns,
                "signal_close": format(close + adjustment, "f"),
                "raw_close": format(close, "f"),
                "execution_instrument_id": event.instrument_id,
                "rolled": rolled,
                "roll_adjustment": format(adjustment, "f"),
            }
        )
        previous = event
    return rows

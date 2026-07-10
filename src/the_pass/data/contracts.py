"""Lossless, engine-neutral market data contracts."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Iterable, Mapping


class EventType(str, Enum):
    INSTRUMENT_DEFINITION = "instrument_definition"
    BAR = "bar"
    TRADE = "trade"
    QUOTE = "quote"
    BOOK_SNAPSHOT = "book_snapshot"
    BOOK_DELTA = "book_delta"
    FUNDING = "funding"
    OPEN_INTEREST = "open_interest"
    SETTLEMENT = "settlement"
    DECISION = "decision"
    SIMULATED_ORDER = "simulated_order"
    FILL = "fill"
    PORTFOLIO_SNAPSHOT = "portfolio_snapshot"


def decimal_string(value: Decimal | str | int) -> str:
    """Return a non-exponential decimal string without changing precision."""

    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"invalid decimal value: {value!r}") from exc
    if not number.is_finite():
        raise ValueError("decimal values must be finite")
    return format(number, "f")


def canonical_value(value: Any, *, allow_float: bool = False) -> Any:
    if isinstance(value, Decimal):
        return decimal_string(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): canonical_value(value[key], allow_float=allow_float) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [canonical_value(item, allow_float=allow_float) for item in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if allow_float and math.isfinite(value):
            return value
        raise TypeError("floats are not accepted in lossless canonical data; use Decimal")
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def canonical_json_bytes(value: Any, *, allow_float: bool = False) -> bytes:
    return json.dumps(
        canonical_value(value, allow_float=allow_float),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def stable_fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value, allow_float=True)).hexdigest()


@dataclass(frozen=True)
class Instrument:
    instrument_id: str
    symbol: str
    venue: str
    asset_class: str
    tick_size: Decimal
    lot_size: Decimal
    multiplier: Decimal
    quote_currency: str
    contract_type: str
    expiry: str | None = None
    margin_mode: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("instrument_id", "symbol", "venue", "asset_class", "quote_currency"):
            if not getattr(self, field_name):
                raise ValueError(f"{field_name} must not be empty")
        for field_name in ("tick_size", "lot_size", "multiplier"):
            value = getattr(self, field_name)
            if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
                raise ValueError(f"{field_name} must be a positive finite Decimal")

    def as_dict(self) -> dict[str, Any]:
        return {
            "instrument_id": self.instrument_id,
            "symbol": self.symbol,
            "venue": self.venue,
            "asset_class": self.asset_class,
            "tick_size": decimal_string(self.tick_size),
            "lot_size": decimal_string(self.lot_size),
            "multiplier": decimal_string(self.multiplier),
            "quote_currency": self.quote_currency,
            "contract_type": self.contract_type,
            "expiry": self.expiry,
            "margin_mode": self.margin_mode,
        }


@dataclass(frozen=True)
class CanonicalEvent:
    source: str
    venue: str
    asset_class: str
    instrument_id: str
    event_type: EventType
    event_time_ns: int
    receive_time_ns: int
    ingest_id: str
    raw_fingerprint: str
    payload: Mapping[str, Any]
    sequence: int | None = None

    def __post_init__(self) -> None:
        for field_name in ("source", "venue", "asset_class", "instrument_id", "ingest_id"):
            if not getattr(self, field_name):
                raise ValueError(f"{field_name} must not be empty")
        if self.event_time_ns < 0 or self.receive_time_ns < 0:
            raise ValueError("timestamps must be UTC nanoseconds since epoch")
        if self.sequence is not None and self.sequence < 0:
            raise ValueError("sequence must be non-negative")
        if len(self.raw_fingerprint) != 64 or any(char not in "0123456789abcdefABCDEF" for char in self.raw_fingerprint):
            raise ValueError("raw_fingerprint must be a SHA-256 hex digest")
        canonical_value(self.payload)

    @classmethod
    def from_raw(
        cls,
        *,
        raw: Any,
        source: str,
        venue: str,
        asset_class: str,
        instrument_id: str,
        event_type: EventType,
        event_time_ns: int,
        receive_time_ns: int,
        ingest_id: str,
        payload: Mapping[str, Any],
        sequence: int | None = None,
    ) -> "CanonicalEvent":
        return cls(
            source=source,
            venue=venue,
            asset_class=asset_class,
            instrument_id=instrument_id,
            event_type=event_type,
            event_time_ns=event_time_ns,
            receive_time_ns=receive_time_ns,
            ingest_id=ingest_id,
            raw_fingerprint=stable_fingerprint(raw),
            payload=payload,
            sequence=sequence,
        )

    @classmethod
    def from_dict(cls, document: Mapping[str, Any]) -> "CanonicalEvent":
        if document.get("schema_version") != 2:
            raise ValueError("canonical event schema_version must be 2")
        return cls(
            source=str(document["source"]),
            venue=str(document["venue"]),
            asset_class=str(document["asset_class"]),
            instrument_id=str(document["instrument_id"]),
            event_type=EventType(document["event_type"]),
            event_time_ns=int(document["event_time_ns"]),
            receive_time_ns=int(document["receive_time_ns"]),
            sequence=int(document["sequence"]) if document.get("sequence") is not None else None,
            ingest_id=str(document["ingest_id"]),
            raw_fingerprint=str(document["raw_fingerprint"]),
            payload=dict(document["payload"]),
        )

    def sort_key(self) -> tuple[int, int, int, str]:
        sequence = self.sequence if self.sequence is not None else 2**63 - 1
        return (self.event_time_ns, sequence, self.receive_time_ns, self.ingest_id)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "source": self.source,
            "venue": self.venue,
            "asset_class": self.asset_class,
            "instrument_id": self.instrument_id,
            "event_type": self.event_type.value,
            "event_time_ns": self.event_time_ns,
            "receive_time_ns": self.receive_time_ns,
            "sequence": self.sequence,
            "ingest_id": self.ingest_id,
            "raw_fingerprint": self.raw_fingerprint,
            "payload": canonical_value(self.payload),
        }


def build_instrument_registry(
    registry_id: str,
    source: str,
    instruments: Iterable[Instrument],
    *,
    created_at: str,
) -> dict[str, Any]:
    rows = sorted((instrument.as_dict() for instrument in instruments), key=lambda row: row["instrument_id"])
    if not rows:
        raise ValueError("instrument registry must contain at least one instrument")
    duplicate_ids = {row["instrument_id"] for row in rows if sum(item["instrument_id"] == row["instrument_id"] for item in rows) > 1}
    if duplicate_ids:
        raise ValueError(f"duplicate instrument ids: {', '.join(sorted(duplicate_ids))}")
    core = {
        "schema_version": 2,
        "registry_id": registry_id,
        "created_at": created_at,
        "source": source,
        "instruments": rows,
    }
    return {**core, "fingerprint": stable_fingerprint(core)}

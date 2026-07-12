"""Deterministic canonical-event quality checks."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from .contracts import CanonicalEvent, EventType


@dataclass(frozen=True)
class QualityPolicy:
    expected_interval_ns: int | None = None
    stale_after_ns: int | None = None
    outlier_return: Decimal = Decimal("0.50")
    requested_start_ns: int | None = None
    requested_end_ns: int | None = None
    session_gap_intervals: tuple[tuple[int, int], ...] = ()
    roll_gap_intervals: tuple[tuple[int, int], ...] = ()
    fixed_interval_event_types: tuple[EventType, ...] = (EventType.BAR,)

    def __post_init__(self) -> None:
        for field_name in ("expected_interval_ns", "stale_after_ns"):
            value = getattr(self, field_name)
            if value is not None and (isinstance(value, bool) or value <= 0):
                raise ValueError(f"{field_name} must be positive when provided")
        if self.outlier_return < 0 or not self.outlier_return.is_finite():
            raise ValueError("outlier_return must be non-negative and finite")
        if (
            self.requested_start_ns is not None
            and self.requested_end_ns is not None
            and self.requested_start_ns >= self.requested_end_ns
        ):
            raise ValueError("requested_start_ns must be earlier than requested_end_ns")
        for interval in (*self.session_gap_intervals, *self.roll_gap_intervals):
            if interval[0] >= interval[1]:
                raise ValueError("allowed gap intervals must have start earlier than end")


CHECK_DEFINITIONS = (
    ("missing_intervals", "error"),
    ("duplicates", "error"),
    ("timestamp_disorder", "error"),
    ("sequence_gaps", "error"),
    ("invalid_price_size", "critical"),
    ("crossed_book", "critical"),
    ("stale_book", "error"),
    ("outliers", "warning"),
    ("timezone", "critical"),
    ("session_gaps", "warning"),
    ("roll_gaps", "warning"),
    ("provider_truncation", "error"),
    ("negative_receive_latency", "critical"),
)


def _decimal(value: Any) -> Decimal | None:
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, (str, int)) and not isinstance(value, bool):
        try:
            converted = Decimal(str(value))
        except InvalidOperation:
            return None
        return converted if converted.is_finite() else None
    return None


def _record(affected: dict[str, list[str]], code: str, value: str) -> None:
    affected[code].append(value)


def _interval_overlaps(interval: tuple[int, int], allowed: tuple[tuple[int, int], ...]) -> bool:
    return any(interval[0] >= start and interval[1] <= end for start, end in allowed)


def build_quality_report(
    dataset_id: str,
    events: Iterable[CanonicalEvent],
    *,
    policy: QualityPolicy | None = None,
    created_at: str,
) -> dict[str, Any]:
    policy = policy or QualityPolicy()
    original = list(events)
    ordered = sorted(original, key=CanonicalEvent.sort_key)
    affected = {code: [] for code, _severity in CHECK_DEFINITIONS}

    for index in range(1, len(original)):
        if original[index - 1].sort_key() > original[index].sort_key():
            _record(affected, "timestamp_disorder", f"rows:{index - 1}-{index}")

    seen: dict[tuple[Any, ...], int] = {}
    for index, event in enumerate(original):
        identity = (
            event.source,
            event.venue,
            event.instrument_id,
            event.event_type.value,
            event.event_time_ns,
            event.sequence,
        )
        if identity in seen:
            _record(affected, "duplicates", f"rows:{seen[identity]},{index}")
        else:
            seen[identity] = index
        if not isinstance(event.event_time_ns, int) or not isinstance(event.receive_time_ns, int):
            _record(affected, "timezone", f"row:{index}")
        if event.receive_time_ns < event.event_time_ns:
            _record(affected, "negative_receive_latency", f"row:{index}")

        for field in ("price", "size", "open", "high", "low", "close", "volume"):
            if field not in event.payload:
                continue
            value = _decimal(event.payload[field])
            if value is None or value < 0 or (field not in {"volume", "size"} and value == 0):
                _record(affected, "invalid_price_size", f"row:{index}:{field}")

        if event.event_type == EventType.BOOK_SNAPSHOT:
            bids = event.payload.get("bids") or []
            asks = event.payload.get("asks") or []
            bid_prices = [value for level in bids if isinstance(level, (list, tuple)) and level for value in [_decimal(level[0])] if value is not None]
            ask_prices = [value for level in asks if isinstance(level, (list, tuple)) and level for value in [_decimal(level[0])] if value is not None]
            best_bid = max(bid_prices, default=None)
            best_ask = min(ask_prices, default=None)
            if best_bid is not None and best_ask is not None and best_bid >= best_ask:
                _record(affected, "crossed_book", f"row:{index}")

    grouped: dict[tuple[str, str], list[CanonicalEvent]] = {}
    for event in ordered:
        grouped.setdefault((event.instrument_id, event.event_type.value), []).append(event)

    for (instrument_id, event_type), rows in grouped.items():
        for previous, current in zip(rows, rows[1:]):
            if previous.sequence is not None and current.sequence is not None and current.sequence > previous.sequence + 1:
                _record(affected, "sequence_gaps", f"{instrument_id}:{event_type}:{previous.sequence + 1}-{current.sequence - 1}")
            gap = current.event_time_ns - previous.event_time_ns
            if (
                policy.expected_interval_ns
                and EventType(event_type) in policy.fixed_interval_event_types
                and gap > policy.expected_interval_ns
            ):
                interval = (previous.event_time_ns, current.event_time_ns)
                if _interval_overlaps(interval, policy.session_gap_intervals):
                    _record(affected, "session_gaps", f"{instrument_id}:{interval[0]}-{interval[1]}")
                elif _interval_overlaps(interval, policy.roll_gap_intervals):
                    _record(affected, "roll_gaps", f"{instrument_id}:{interval[0]}-{interval[1]}")
                else:
                    _record(affected, "missing_intervals", f"{instrument_id}:{interval[0]}-{interval[1]}")
            if (
                policy.stale_after_ns
                and event_type in {EventType.BOOK_SNAPSHOT.value, EventType.BOOK_DELTA.value, EventType.QUOTE.value}
                and current.receive_time_ns - previous.receive_time_ns > policy.stale_after_ns
            ):
                _record(affected, "stale_book", f"{instrument_id}:{previous.receive_time_ns}-{current.receive_time_ns}")

        if event_type == EventType.BAR.value:
            closes = [(_decimal(row.payload.get("close")), row) for row in rows]
            for (previous_close, _previous), (current_close, current) in zip(closes, closes[1:]):
                if previous_close and current_close is not None:
                    change = abs(current_close / previous_close - Decimal(1))
                    if change > policy.outlier_return:
                        _record(affected, "outliers", f"{instrument_id}:{current.event_time_ns}")

    coverage_groups: dict[tuple[str, str, str], list[CanonicalEvent]] = {}
    for event in ordered:
        coverage_groups.setdefault((event.source, event.venue, event.instrument_id), []).append(event)
    for (source, venue, instrument_id), rows in sorted(coverage_groups.items()):
        label = f"{source}:{venue}:{instrument_id}"
        if policy.requested_start_ns is not None and rows[0].event_time_ns > policy.requested_start_ns:
            _record(affected, "provider_truncation", f"{label}:start:{rows[0].event_time_ns}")
        if policy.requested_end_ns is not None and rows[-1].event_time_ns < policy.requested_end_ns:
            _record(affected, "provider_truncation", f"{label}:end:{rows[-1].event_time_ns}")

    checks = []
    errors = 0
    warnings = 0
    for code, severity in CHECK_DEFINITIONS:
        rows = affected[code]
        if rows and severity in {"error", "critical"}:
            errors += len(rows)
        if rows and severity == "warning":
            warnings += len(rows)
        checks.append(
            {
                "code": code,
                "severity": severity,
                "count": len(rows),
                "affected": rows,
                "message": f"{code.replace('_', ' ')} check found {len(rows)} issue(s)",
            }
        )

    status = "fail" if errors else "warning" if warnings else "pass"
    return {
        "schema_version": 2,
        "id": f"quality-{dataset_id}",
        "created_at": created_at,
        "dataset_id": dataset_id,
        "checks": checks,
        "summary": {"events": len(original), "errors": errors, "warnings": warnings, "status": status},
        "quarantine": bool(errors),
        "promotion_impact": "blocked" if errors else "diagnostic_only" if warnings else "none",
    }


def event_available_for_decision(event: CanonicalEvent, decision_time_ns: int) -> bool:
    """Prevent event-time lookahead: only received events may affect a decision."""

    return event.receive_time_ns <= decision_time_ns

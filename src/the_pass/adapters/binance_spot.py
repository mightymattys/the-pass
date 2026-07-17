"""Binance Spot public market-data adapter."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any, AsyncIterator, Iterable

from the_pass.data.contracts import CanonicalEvent, EventType, Instrument
from the_pass.data.raw_archive import RawResponseArchive

from .base import AdapterCapabilities, FetchRequest, PublicHttpClient, StreamEvidence, manifest_for_events, reconnecting_json_stream


class BinanceSpotAdapter:
    adapter_id = "binance-spot-public"
    rest_base = "https://data-api.binance.vision"
    websocket_base = "wss://data-stream.binance.vision/ws"
    capabilities = AdapterCapabilities(
        event_types=("instrument_definition", "bar", "trade", "book_snapshot", "book_delta"),
        historical_read=True,
        live_read=True,
        authentication="none",
        replay=False,
        timestamp_quality="provider event/close milliseconds plus honest local receive nanoseconds; unclosed bars excluded",
        license_mode="public endpoint; redistribution review required",
        maximum_promotion_mode="diagnostic",
    )

    def __init__(
        self,
        client: PublicHttpClient | None = None,
        *,
        archive: RawResponseArchive | None = None,
        license_reviewed: bool = False,
    ) -> None:
        self.archive = archive
        self.client = client or PublicHttpClient(archive=archive, provider=self.adapter_id)
        if archive is not None and license_reviewed:
            self.capabilities = replace(type(self).capabilities, replay=True, maximum_promotion_mode="research")
        else:
            self.capabilities = type(self).capabilities

    def discover_instruments(self, request: FetchRequest | None = None) -> list[Instrument]:
        params: dict[str, Any] = {}
        symbols = tuple((request.parameters or {}).get("symbols", ())) if request else ()
        if symbols:
            params["symbols"] = json.dumps(list(symbols), separators=(",", ":"))
        raw = self.client.get_json(f"{self.rest_base}/api/v3/exchangeInfo", params=params)
        instruments = []
        for row in raw.get("symbols", []):
            if row.get("status") != "TRADING":
                continue
            filters = {item["filterType"]: item for item in row.get("filters", [])}
            price_filter = filters.get("PRICE_FILTER", {})
            lot_filter = filters.get("LOT_SIZE", {})
            instruments.append(
                Instrument(
                    instrument_id=row["symbol"],
                    symbol=row["symbol"],
                    venue="binance",
                    asset_class="crypto_spot",
                    tick_size=Decimal(price_filter["tickSize"]),
                    lot_size=Decimal(lot_filter["stepSize"]),
                    multiplier=Decimal(1),
                    quote_currency=row["quoteAsset"],
                    contract_type="spot",
                )
            )
        return sorted(instruments, key=lambda item: item.instrument_id)

    def fetch_raw(self, request: FetchRequest) -> Any:
        if not request.instrument_id:
            raise ValueError("Binance fetch requires instrument_id")
        params: dict[str, Any] = {"symbol": request.instrument_id}
        page_limit = min(request.limit or 1_000, 1_000)
        params["limit"] = page_limit
        if request.start_ns is not None:
            params["startTime"] = request.start_ns // 1_000_000
        if request.end_ns is not None:
            params["endTime"] = request.end_ns // 1_000_000 - 1
        if request.kind == "klines":
            params["interval"] = (request.parameters or {}).get("interval", "1m")
            endpoint = "/api/v3/klines"
        elif request.kind == "trades":
            endpoint = "/api/v3/aggTrades"
        elif request.kind == "book":
            endpoint = "/api/v3/depth"
        else:
            raise ValueError(f"unsupported Binance read kind: {request.kind}")
        url = f"{self.rest_base}{endpoint}"
        if request.kind == "book" or request.start_ns is None or request.end_ns is None:
            return self.client.get_json(url, params=params)

        rows: list[Any] = []
        page_params = dict(params)
        end_ms = request.end_ns // 1_000_000
        while True:
            page = self.client.get_json(url, params=page_params)
            if not isinstance(page, list):
                raise TypeError("Binance paginated response must be a list")
            if request.kind == "klines":
                rows.extend(row for row in page if int(row[0]) < end_ms)
            else:
                rows.extend(row for row in page if int(row["T"]) < end_ms)
            if len(page) < page_limit or not page:
                break
            if request.kind == "klines":
                next_start = int(page[-1][0]) + 1
                if next_start >= end_ms:
                    break
                page_params["startTime"] = next_start
            else:
                if int(page[-1]["T"]) >= end_ms:
                    break
                page_params = {
                    "symbol": request.instrument_id,
                    "limit": page_limit,
                    "fromId": int(page[-1]["a"]) + 1,
                }
        return rows

    def normalize(self, raw: Any, request: FetchRequest, *, receive_time_ns: int) -> list[CanonicalEvent]:
        instrument_id = request.instrument_id or ""
        if request.kind == "klines":
            events = []
            for row in raw:
                close_time_ns = int(row[6]) * 1_000_000
                if close_time_ns > receive_time_ns:
                    continue
                events.append(
                    CanonicalEvent.from_raw(
                        raw=row,
                        source=self.adapter_id,
                        venue="binance",
                        asset_class="crypto_spot",
                        instrument_id=instrument_id,
                        event_type=EventType.BAR,
                        event_time_ns=int(row[0]) * 1_000_000,
                        receive_time_ns=receive_time_ns,
                        ingest_id=f"binance-kline-{instrument_id}-{row[0]}",
                        payload={
                            "open": Decimal(row[1]),
                            "high": Decimal(row[2]),
                            "low": Decimal(row[3]),
                            "close": Decimal(row[4]),
                            "volume": Decimal(row[5]),
                            "close_time_ns": close_time_ns,
                            "quote_volume": Decimal(row[7]),
                            "trade_count": int(row[8]),
                        },
                    )
                )
            return events
        if request.kind == "trades":
            return [
                CanonicalEvent.from_raw(
                    raw=row,
                    source=self.adapter_id,
                    venue="binance",
                    asset_class="crypto_spot",
                    instrument_id=instrument_id,
                    event_type=EventType.TRADE,
                    event_time_ns=int(row["T"]) * 1_000_000,
                    receive_time_ns=receive_time_ns,
                    ingest_id=f"binance-trade-{instrument_id}-{row['a']}",
                    sequence=int(row["a"]),
                    payload={"price": Decimal(row["p"]), "size": Decimal(row["q"]), "buyer_maker": bool(row["m"])},
                )
                for row in raw
            ]
        if request.kind == "book":
            return [
                CanonicalEvent.from_raw(
                    raw=raw,
                    source=self.adapter_id,
                    venue="binance",
                    asset_class="crypto_spot",
                    instrument_id=instrument_id,
                    event_type=EventType.BOOK_SNAPSHOT,
                    event_time_ns=receive_time_ns,
                    receive_time_ns=receive_time_ns,
                    ingest_id=f"binance-book-{instrument_id}-{raw['lastUpdateId']}",
                    sequence=int(raw["lastUpdateId"]),
                    payload={"bids": raw.get("bids", []), "asks": raw.get("asks", [])},
                )
            ]
        raise ValueError(f"unsupported Binance normalize kind: {request.kind}")

    def cross_check(self, primary: Iterable[CanonicalEvent], reference: Any) -> dict[str, Any]:
        reference_by_time = {int(row["event_time_ns"]): Decimal(str(row["close"])) for row in reference}
        deviations = []
        for event in primary:
            if event.event_type != EventType.BAR or event.event_time_ns not in reference_by_time:
                continue
            primary_close = Decimal(str(event.payload["close"]))
            reference_close = reference_by_time[event.event_time_ns]
            deviations.append(abs(primary_close / reference_close - Decimal(1)) * Decimal(10_000))
        maximum = max(deviations) if deviations else None
        return {
            "status": "pass" if maximum is not None and maximum <= Decimal("10") else "warning",
            "matched": len(deviations),
            "max_close_deviation_bps": format(maximum, "f") if maximum is not None else None,
            "action": "record_only_never_rewrite",
        }

    def build_manifest(self, events: Iterable[CanonicalEvent], *, raw_path: Path, quality_report: dict[str, Any]) -> dict[str, Any]:
        return manifest_for_events(
            self.adapter_id,
            events,
            raw_path=raw_path,
            quality_report=quality_report,
            endpoint=f"{self.rest_base}/api/v3",
            license_note="Binance public market-data terms require review before redistribution",
        )

    def cost_snapshot(self, instrument_id: str, *, observed_at_ns: int) -> dict[str, Any]:
        return {
            "instrument_id": instrument_id,
            "observed_at_ns": observed_at_ns,
            "status": "unavailable_publicly",
            "reason": "account fee tier is not available from unauthenticated market-data endpoints",
        }

    async def market_stream(
        self,
        symbol: str,
        *,
        archive: RawResponseArchive,
        evidence: StreamEvidence | None = None,
        channel: str = "trade",
    ) -> AsyncIterator[dict[str, Any]]:
        if channel not in {"trade", "depth"}:
            raise ValueError("channel must be trade or depth")
        stream = f"{symbol.lower()}@{channel}"
        async for payload in reconnecting_json_stream(
            url=f"{self.websocket_base}/{stream}",
            provider=self.adapter_id,
            stream=stream,
            archive=archive,
            evidence=evidence,
        ):
            yield payload

"""Polymarket public discovery, book, fee, and resolution adapter."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from decimal import Decimal
from pathlib import Path
from typing import Any, AsyncIterator, Iterable

from the_pass.data.contracts import CanonicalEvent, EventType, Instrument
from the_pass.data.raw_archive import RawResponseArchive

from .base import AdapterCapabilities, FetchRequest, PublicHttpClient, StreamEvidence, manifest_for_events, reconnecting_json_stream


class PolymarketAdapter:
    adapter_id = "polymarket-public"
    gamma_base = "https://gamma-api.polymarket.com"
    clob_base = "https://clob.polymarket.com"
    websocket_url = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    capabilities = AdapterCapabilities(
        event_types=("instrument_definition", "book_snapshot", "book_delta", "trade", "settlement"),
        historical_read=False,
        live_read=True,
        authentication="none",
        replay=False,
        timestamp_quality="provider timestamp plus local receive nanoseconds",
        license_mode="public endpoints; terms and archival review required",
        maximum_promotion_mode="diagnostic",
    )

    def __init__(
        self,
        client: PublicHttpClient | None = None,
        *,
        archive: RawResponseArchive | None = None,
        license_reviewed: bool = False,
        resolution_reviewed: bool = False,
    ) -> None:
        self.archive = archive
        self.client = client or PublicHttpClient(archive=archive, provider=self.adapter_id)
        if archive is not None and license_reviewed and resolution_reviewed:
            self.capabilities = replace(type(self).capabilities, replay=True, maximum_promotion_mode="research")
        else:
            self.capabilities = type(self).capabilities

    def discover_instruments(self, request: FetchRequest | None = None) -> list[Instrument]:
        params: dict[str, Any] = {"active": "true", "closed": "false", "limit": 100}
        if request and request.limit:
            params["limit"] = request.limit
        rows = self.client.get_json(f"{self.gamma_base}/markets", params=params)
        instruments = []
        for market in rows:
            token_ids = market.get("clobTokenIds") or []
            outcomes = market.get("outcomes") or []
            if isinstance(token_ids, str):
                token_ids = json.loads(token_ids)
            if isinstance(outcomes, str):
                outcomes = json.loads(outcomes)
            for token_id, outcome in zip(token_ids, outcomes):
                instruments.append(
                    Instrument(
                        instrument_id=str(token_id),
                        symbol=f"{market.get('slug', market.get('id'))}:{outcome}",
                        venue="polymarket",
                        asset_class="prediction_market",
                        tick_size=Decimal(str(market.get("orderPriceMinTickSize") or "0.01")),
                        lot_size=Decimal(str(market.get("orderMinSize") or "1")),
                        multiplier=Decimal(1),
                        quote_currency="pUSD",
                        contract_type="prediction_outcome",
                    )
                )
        return sorted(instruments, key=lambda item: item.instrument_id)

    def fetch_raw(self, request: FetchRequest) -> Any:
        if request.kind == "markets":
            return self.client.get_json(f"{self.gamma_base}/markets", params=request.parameters)
        if not request.instrument_id:
            raise ValueError("Polymarket CLOB reads require token instrument_id")
        if request.kind == "book":
            return self.client.get_json(f"{self.clob_base}/book", params={"token_id": request.instrument_id})
        if request.kind == "fee_rate":
            return self.client.get_json(f"{self.clob_base}/fee-rate/{request.instrument_id}")
        if request.kind == "price_history":
            params = {"market": request.instrument_id, **dict(request.parameters or {})}
            return self.client.get_json(f"{self.clob_base}/prices-history", params=params)
        raise ValueError(f"unsupported Polymarket read kind: {request.kind}")

    def normalize(self, raw: Any, request: FetchRequest, *, receive_time_ns: int) -> list[CanonicalEvent]:
        if request.kind != "book" or not request.instrument_id:
            raise ValueError("canonical normalization currently supports Polymarket books")
        timestamp = int(raw.get("timestamp", receive_time_ns))
        if timestamp < 10**15:
            timestamp *= 1_000_000
        sequence_value = raw.get("sequence")
        sequence = int(sequence_value) if sequence_value is not None else None
        return [
            CanonicalEvent.from_raw(
                raw=raw,
                source=self.adapter_id,
                venue="polymarket",
                asset_class="prediction_market",
                instrument_id=request.instrument_id,
                event_type=EventType.BOOK_SNAPSHOT,
                event_time_ns=timestamp,
                receive_time_ns=receive_time_ns,
                ingest_id=f"polymarket-book-{request.instrument_id}-{receive_time_ns}",
                sequence=sequence,
                payload={
                    "market": raw.get("market"),
                    "asset_id": raw.get("asset_id", request.instrument_id),
                    "hash": raw.get("hash"),
                    "bids": [[level["price"], level["size"]] for level in raw.get("bids", [])],
                    "asks": [[level["price"], level["size"]] for level in raw.get("asks", [])],
                },
            )
        ]

    def cross_check(self, primary: Iterable[CanonicalEvent], reference: Any) -> dict[str, Any]:
        rows = list(primary)
        reference_hash = reference.get("hash") if isinstance(reference, dict) else None
        hash_matches = bool(rows) and rows[-1].payload.get("hash") == reference_hash
        complements = reference.get("complementary_best_asks") if isinstance(reference, dict) else None
        complement_sum = None
        if isinstance(complements, list) and len(complements) == 2:
            complement_sum = sum(Decimal(str(value)) for value in complements)
        return {
            "status": "pass" if hash_matches and (complement_sum is None or complement_sum >= Decimal(1)) else "warning",
            "rest_websocket_hash_match": hash_matches,
            "complementary_best_ask_sum": format(complement_sum, "f") if complement_sum is not None else None,
            "action": "resync_on_hash_or_sequence_mismatch",
        }

    def build_manifest(self, events: Iterable[CanonicalEvent], *, raw_path: Path, quality_report: dict[str, Any]) -> dict[str, Any]:
        return manifest_for_events(
            self.adapter_id,
            events,
            raw_path=raw_path,
            quality_report=quality_report,
            endpoint=f"{self.gamma_base}/markets and {self.clob_base}/book",
            license_note="Polymarket public API terms and market resolution semantics require review",
        )

    def cost_snapshot(self, instrument_id: str, *, observed_at_ns: int) -> dict[str, Any]:
        raw = self.fetch_raw(FetchRequest(kind="fee_rate", instrument_id=instrument_id))
        fee_rate = raw.get("base_fee") if isinstance(raw, dict) else raw
        return {
            "instrument_id": instrument_id,
            "observed_at_ns": observed_at_ns,
            "fee_rate": str(fee_rate),
            "source": f"{self.clob_base}/fee-rate/{{token_id}}",
            "dynamic": True,
        }

    def settlement_snapshot(self, market_id: str, *, observed_at_ns: int) -> dict[str, Any]:
        rows = self.client.get_json(f"{self.gamma_base}/markets/{market_id}")
        return {"market_id": market_id, "observed_at_ns": observed_at_ns, "resolution": rows}

    async def market_stream(
        self,
        token_ids: list[str],
        *,
        archive: RawResponseArchive,
        evidence: StreamEvidence | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        if not token_ids:
            raise ValueError("at least one token id is required")
        async for payload in reconnecting_json_stream(
            url=self.websocket_url,
            provider=self.adapter_id,
            stream="market",
            archive=archive,
            subscription={"assets_ids": token_ids, "type": "market", "custom_feature_enabled": True},
            evidence=evidence,
        ):
            yield payload


@dataclass
class PolymarketBookState:
    instrument_id: str
    bids: dict[Decimal, Decimal] = field(default_factory=dict)
    asks: dict[Decimal, Decimal] = field(default_factory=dict)
    sequence: int | None = None
    state_hash: str | None = None
    resync_required: bool = True

    def apply_snapshot(self, event: CanonicalEvent) -> None:
        if event.event_type != EventType.BOOK_SNAPSHOT or event.instrument_id != self.instrument_id:
            raise ValueError("book snapshot does not match state")
        self.bids = {Decimal(str(price)): Decimal(str(size)) for price, size in event.payload.get("bids", [])}
        self.asks = {Decimal(str(price)): Decimal(str(size)) for price, size in event.payload.get("asks", [])}
        self.sequence = event.sequence
        self.state_hash = str(event.payload.get("hash")) if event.payload.get("hash") is not None else None
        self.resync_required = False

    def apply_delta(self, event: CanonicalEvent) -> bool:
        if event.event_type != EventType.BOOK_DELTA or event.instrument_id != self.instrument_id:
            raise ValueError("book delta does not match state")
        previous_hash = event.payload.get("previous_hash")
        sequence_gap = self.sequence is not None and event.sequence is not None and event.sequence != self.sequence + 1
        hash_gap = previous_hash is not None and self.state_hash is not None and previous_hash != self.state_hash
        if self.resync_required or sequence_gap or hash_gap:
            self.resync_required = True
            return False
        for change in event.payload.get("changes", []):
            side = change.get("side")
            levels = self.bids if side == "bid" else self.asks if side == "ask" else None
            if levels is None:
                self.resync_required = True
                return False
            price = Decimal(str(change["price"]))
            size = Decimal(str(change["size"]))
            if size == 0:
                levels.pop(price, None)
            elif size > 0:
                levels[price] = size
            else:
                self.resync_required = True
                return False
        self.sequence = event.sequence
        self.state_hash = str(event.payload.get("hash")) if event.payload.get("hash") is not None else self.state_hash
        return True

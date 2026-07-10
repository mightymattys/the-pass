#!/usr/bin/env python3
"""Opt-in, read-only public adapter smoke test with metadata-only output."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from the_pass.adapters import (  # noqa: E402
    BinanceSpotAdapter,
    DatabentoCompatibleFuturesAdapter,
    FetchRequest,
    PolymarketAdapter,
)


def now_rfc3339() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def run_smoke() -> dict[str, object]:
    receive_time_ns = time.time_ns()
    binance = BinanceSpotAdapter()
    binance_results = []
    for symbol in ("BTCUSDT", "ETHUSDT"):
        request = FetchRequest(kind="klines", instrument_id=symbol, limit=2, parameters={"interval": "1m"})
        events = binance.normalize(binance.fetch_raw(request), request, receive_time_ns=receive_time_ns)
        binance_results.append(
            {
                "instrument_id": symbol,
                "events": len(events),
                "ordered": events == sorted(events, key=type(events[0]).sort_key),
                "credentials_used": False,
            }
        )

    polymarket = PolymarketAdapter()
    instruments = polymarket.discover_instruments(FetchRequest(kind="markets", limit=20))
    if not instruments:
        raise RuntimeError("Polymarket discovery returned no public CLOB instruments")
    instrument_id = instruments[0].instrument_id
    book_request = FetchRequest(kind="book", instrument_id=instrument_id)
    book_raw = polymarket.fetch_raw(book_request)
    book_events = polymarket.normalize(book_raw, book_request, receive_time_ns=time.time_ns())
    fee = polymarket.cost_snapshot(instrument_id, observed_at_ns=time.time_ns())

    futures = DatabentoCompatibleFuturesAdapter(ROOT / "tests" / "fixtures" / "futures")
    futures_raw = futures.fetch_raw(FetchRequest(kind="bars"))
    futures_events = futures.normalize(futures_raw, FetchRequest(kind="bars"), receive_time_ns=receive_time_ns)

    return {
        "schema_version": 1,
        "created_at": now_rfc3339(),
        "mode": "public_read_only",
        "network_opt_in": True,
        "binance": {
            "status": "pass",
            "rest_base": binance.rest_base,
            "results": binance_results,
        },
        "polymarket": {
            "status": "pass",
            "discovered_instruments": len(instruments),
            "book_events": len(book_events),
            "book_has_hash": bool(book_events[0].payload.get("hash")),
            "dynamic_fee_observed": fee.get("fee_rate") is not None,
            "credentials_used": False,
        },
        "futures_fixture": {
            "status": "pass",
            "events": len(futures_events),
            "promotion_mode": futures.capabilities.maximum_promotion_mode,
        },
        "safety": {
            "authenticated_channels_used": False,
            "credentials_used": False,
            "writes_to_provider": False,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)
    try:
        report = run_smoke()
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if args.format == "json":
            print(json.dumps({"ok": True, "status": "pass", "artifact_paths": [str(args.output)] if args.output else [], "issues": [], "receipt_id": None, "report": report}, indent=2, sort_keys=True))
        else:
            print("public read-only adapter smoke passed")
        return 0
    except Exception as exc:
        if args.format == "json":
            print(json.dumps({"ok": False, "status": "error", "artifact_paths": [], "issues": [{"path": "$", "message": str(exc)}], "receipt_id": None}))
        else:
            print(f"public adapter smoke failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Opt-in, read-only public adapter smoke test with metadata-only output."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from the_pass.adapters import (  # noqa: E402
    BinanceSpotAdapter,
    DatabentoCompatibleFuturesAdapter,
    FetchRequest,
    PolymarketAdapter,
)
from the_pass.data.contracts import CanonicalEvent, stable_fingerprint  # noqa: E402
from the_pass.data.ingest import OfflineIngestService  # noqa: E402
from the_pass.engine.package import (  # noqa: E402
    preregister_search_space,
    write_run_package,
)
from the_pass.strategy_runtime import (  # noqa: E402
    load_execution_config,
    load_strategy_descriptor,
    run_strategy_verified,
    runner_result_from_document,
)


def now_rfc3339() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, object]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"expected JSON object: {path}")
    return document


def load_events(path: Path) -> list[CanonicalEvent]:
    return [
        CanonicalEvent.from_dict(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def package_id(path: Path) -> str:
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not rows or not isinstance(rows[-1].get("package_id"), str):
        raise ValueError("diagnostic package ledger has no package_id")
    return rows[-1]["package_id"]


def public_pipeline(
    binance: BinanceSpotAdapter,
    polymarket: PolymarketAdapter,
    instrument_id: str,
) -> dict[str, object]:
    """Build bounded diagnostic packages while retaining only metadata fingerprints."""

    with tempfile.TemporaryDirectory(prefix="the-pass-public-pipeline-") as tmp:
        root = Path(tmp)
        service = OfflineIngestService()

        binance_request = FetchRequest(
            kind="klines",
            instrument_id="BTCUSDT",
            limit=16,
            parameters={"interval": "1m"},
        )
        binance_ingest = service.ingest(
            binance,
            binance_request,
            root / "binance-data",
        )
        events = load_events(binance_ingest.canonical_path)
        example_root = ROOT / "examples" / "custom-strategy"
        descriptor = load_strategy_descriptor(
            example_root / "binance-descriptor.json",
            workspace_root=example_root,
        )
        execution = load_execution_config(example_root / "execution.json")
        runtime = run_strategy_verified(
            events,
            descriptor=descriptor,
            execution=execution,
            workspace_root=example_root,
        )
        search_space = {
            "schema_version": 1,
            "strategy_id": descriptor.strategy_id,
            "variants": [descriptor.config],
        }
        run_package = root / "binance-package"
        preregister_search_space(run_package, search_space)
        write_run_package(
            run_package,
            result=runner_result_from_document(runtime),
            events=events,
            search_space=search_space,
            initial_cash=execution.initial_cash,
            asset_class=descriptor.asset_class,
            random_seed=None,
            strategy_spec_document=load_json(
                example_root / "binance-strategy-spec.json"
            ),
            data_manifest_document=binance_ingest.data_manifest,
            quality_report_document=binance_ingest.quality_report,
            command="scripts/smoke_public_adapters.py --network-opt-in",
            runtime_evidence=runtime,
            created_at=str(binance_ingest.quality_report["created_at"]),
        )

        polymarket_request = FetchRequest(kind="book", instrument_id=instrument_id)
        polymarket_ingest = service.ingest(
            polymarket,
            polymarket_request,
            root / "polymarket-data",
        )
        book = load_events(polymarket_ingest.canonical_path)[0]
        bids = [Decimal(str(level[0])) for level in book.payload.get("bids", [])]
        asks = [Decimal(str(level[0])) for level in book.payload.get("asks", [])]
        scanner_core = {
            "schema_version": 1,
            "mode": "diagnostic_read_only",
            "instrument_id": instrument_id,
            "canonical_fingerprint": polymarket_ingest.canonical_fingerprint,
            "manifest_fingerprint": stable_fingerprint(
                polymarket_ingest.data_manifest
            ),
            "quality_fingerprint": stable_fingerprint(
                polymarket_ingest.quality_report
            ),
            "cost_snapshot": load_json(polymarket_ingest.receipt_path)[
                "cost_snapshot"
            ],
            "best_bid": format(max(bids), "f") if bids else None,
            "best_ask": format(min(asks), "f") if asks else None,
            "spread": format(min(asks) - max(bids), "f") if bids and asks else None,
            "promotion_eligible": False,
            "blockers": [
                "single REST snapshot is not replay evidence",
                "complementary outcome and resolution semantics require separate evidence",
            ],
        }
        scanner_report = {
            **scanner_core,
            "report_fingerprint": stable_fingerprint(scanner_core),
        }
        scanner_package = {
            "data_manifest": polymarket_ingest.data_manifest,
            "quality_report": polymarket_ingest.quality_report,
            "ingest_receipt_fingerprint": load_json(polymarket_ingest.receipt_path)[
                "receipt_fingerprint"
            ],
            "scanner_report": scanner_report,
        }

        return {
            "status": "pass",
            "payload_retention": "temporary_only_metadata_reported",
            "promotion_eligible": False,
            "binance": {
                "event_count": binance_ingest.event_count,
                "canonical_fingerprint": binance_ingest.canonical_fingerprint,
                "run_package_id": package_id(
                    run_package / "receipt-ledger.jsonl"
                ),
                "runtime_result_fingerprint": runtime["result_fingerprint"],
                "determinism_verified": runtime["determinism_verified"],
                "verdict": load_json(run_package / "verdict_report.json")[
                    "verdict"
                ],
            },
            "polymarket": {
                "event_count": polymarket_ingest.event_count,
                "canonical_fingerprint": polymarket_ingest.canonical_fingerprint,
                "scanner_package_fingerprint": stable_fingerprint(scanner_package),
                "scanner_report": scanner_report,
            },
        }


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
    pipeline = public_pipeline(binance, polymarket, instrument_id)

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
        "diagnostic_pipeline": pipeline,
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
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "created_at": now_rfc3339(),
                        "mode": "public_read_only",
                        "network_opt_in": True,
                        "status": "error",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "safety": {
                            "authenticated_channels_used": False,
                            "credentials_used": False,
                            "writes_to_provider": False,
                        },
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
        if args.format == "json":
            print(json.dumps({"ok": False, "status": "error", "artifact_paths": [str(args.output)] if args.output else [], "issues": [{"path": "$", "message": str(exc)}], "receipt_id": None}))
        else:
            print(f"public adapter smoke failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import json
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from decimal import Decimal
from pathlib import Path

from the_pass.adapters import (
    BinanceSpotAdapter,
    DatabentoCompatibleFuturesAdapter,
    FetchRequest,
    PolymarketAdapter,
    PolymarketBookState,
    ReadOnlyAdapter,
    build_volume_rolled_series,
)
from the_pass.data import (
    CanonicalEvent,
    DuckDBQueryLayer,
    EventType,
    ImmutableParquetStore,
    Instrument,
    PartitionExistsError,
    QualityPolicy,
    RawResponseArchive,
    build_bar_features,
    build_instrument_registry,
    build_quality_report,
    stable_fingerprint,
)
from the_pass.data.quality import event_available_for_decision
from the_pass.cli import main as cli_main
from the_pass.validator import validate_artifact


ROOT = Path(__file__).resolve().parents[1]
FUTURES_FIXTURE = ROOT / "tests" / "fixtures" / "futures"


class FakeResponse:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self) -> object:
        return self.payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")


class FakePublicClient:
    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, object]] = []

    def get_json(self, url: str, *, params: object = None) -> object:
        self.calls.append((url, params))
        return self.responses[url]


class BinanceWindowClient:
    def __init__(self, rows: list[list[object]]) -> None:
        self.rows = rows
        self.calls: list[dict[str, object]] = []

    def get_json(self, url: str, *, params: object = None) -> object:
        assert isinstance(params, dict)
        self.calls.append(dict(params))
        start = int(params.get("startTime", 0))
        end = int(params.get("endTime", 2**63 - 1))
        limit = int(params["limit"])
        return [row for row in self.rows if start <= int(row[0]) <= end][
            :limit
        ]


def binance_kline(open_time_ms: int, close: str = "100") -> list[object]:
    return [
        open_time_ms,
        close,
        close,
        close,
        close,
        "10",
        open_time_ms + 59_999,
        "1000",
        5,
    ]


def bar(
    timestamp: int,
    close: str,
    *,
    sequence: int,
    receive_offset: int = 100,
    ingest_id: str | None = None,
) -> CanonicalEvent:
    raw = {"timestamp": timestamp, "close": close, "sequence": sequence}
    return CanonicalEvent.from_raw(
        raw=raw,
        source="fixture",
        venue="test",
        asset_class="synthetic",
        instrument_id="TEST",
        event_type=EventType.BAR,
        event_time_ns=timestamp,
        receive_time_ns=timestamp + receive_offset,
        ingest_id=ingest_id or f"bar-{timestamp}-{sequence}",
        sequence=sequence,
        payload={"open": Decimal(close), "high": Decimal(close), "low": Decimal(close), "close": Decimal(close), "volume": Decimal(1)},
    )


class CanonicalContractTests(unittest.TestCase):
    def test_float_payload_is_rejected_and_decimal_is_lossless(self) -> None:
        with self.assertRaises(TypeError):
            CanonicalEvent.from_raw(
                raw={"price": 1.1},
                source="fixture",
                venue="test",
                asset_class="synthetic",
                instrument_id="TEST",
                event_type=EventType.TRADE,
                event_time_ns=1,
                receive_time_ns=2,
                ingest_id="float",
                payload={"price": 1.1},
            )
        event = bar(1, "1.230000000000000001", sequence=1)
        self.assertEqual(event.as_dict()["payload"]["close"], "1.230000000000000001")

    def test_deterministic_sort_and_feature_fingerprint(self) -> None:
        first = bar(1_000, "100", sequence=1)
        second = bar(2_000, "110", sequence=2)
        config = {"window": 1}
        left = build_bar_features(
            [second, first],
            dataset_fingerprint=stable_fingerprint([first.as_dict(), second.as_dict()]),
            code_version="test",
            config=config,
            created_at="2026-07-10T00:00:00Z",
        )
        right = build_bar_features(
            [first, second],
            dataset_fingerprint=stable_fingerprint([first.as_dict(), second.as_dict()]),
            code_version="test",
            config=config,
            created_at="2026-07-10T00:00:00Z",
        )
        self.assertEqual(left, right)
        self.assertEqual(left.rows[1]["return_1"], "0.1")

    def test_feature_build_rejects_events_that_do_not_match_fingerprint(self) -> None:
        first = bar(1_000, "100", sequence=1)
        blessed = stable_fingerprint([first.as_dict()])
        edited = bar(1_000, "101", sequence=1)
        with self.assertRaisesRegex(ValueError, "dataset_fingerprint"):
            build_bar_features(
                [edited],
                dataset_fingerprint=blessed,
                code_version="test",
                config={},
                created_at="2026-07-10T00:00:00Z",
            )

    def test_receive_time_controls_decision_availability(self) -> None:
        event = bar(100, "10", sequence=1, receive_offset=50)
        self.assertFalse(event_available_for_decision(event, 149))
        self.assertTrue(event_available_for_decision(event, 150))

    def test_registry_fingerprint_is_order_independent_and_valid(self) -> None:
        instruments = [
            Instrument("B", "B", "test", "synthetic", Decimal("0.01"), Decimal("1"), Decimal("1"), "USD", "synthetic"),
            Instrument("A", "A", "test", "synthetic", Decimal("0.01"), Decimal("1"), Decimal("1"), "USD", "synthetic"),
        ]
        left = build_instrument_registry("registry", "fixture", instruments, created_at="2026-07-10T00:00:00Z")
        right = build_instrument_registry("registry", "fixture", reversed(instruments), created_at="2026-07-10T00:00:00Z")
        self.assertEqual(left, right)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "instrument_registry.json"
            path.write_text(json.dumps(left), encoding="utf-8")
            result = validate_artifact(path, artifact_type="instrument_registry")
        self.assertTrue(result.ok, [issue.as_dict() for issue in result.issues])


class QualityTests(unittest.TestCase):
    def test_quality_mutations_block_promotion(self) -> None:
        first = bar(100, "100", sequence=1, receive_offset=100)
        duplicate = bar(100, "100", sequence=1, receive_offset=100, ingest_id="duplicate")
        gap = bar(400, "200", sequence=3, receive_offset=-1)
        report = build_quality_report(
            "mutated",
            [gap, first, duplicate],
            policy=QualityPolicy(
                expected_interval_ns=100,
                outlier_return=Decimal("0.5"),
                requested_start_ns=0,
                requested_end_ns=500,
            ),
            created_at="2026-07-10T00:00:00Z",
        )
        counts = {check["code"]: check["count"] for check in report["checks"]}
        self.assertGreater(counts["timestamp_disorder"], 0)
        self.assertGreater(counts["duplicates"], 0)
        self.assertGreater(counts["sequence_gaps"], 0)
        self.assertGreater(counts["missing_intervals"], 0)
        self.assertGreater(counts["outliers"], 0)
        self.assertGreater(counts["provider_truncation"], 0)
        self.assertGreater(counts["negative_receive_latency"], 0)
        self.assertTrue(report["quarantine"])
        self.assertEqual(report["promotion_impact"], "blocked")

    def test_conflicting_market_key_is_duplicate_even_when_raw_payload_differs(self) -> None:
        first = bar(100, "100", sequence=1, ingest_id="first")
        conflicting = bar(100, "101", sequence=1, ingest_id="second")
        report = build_quality_report(
            "conflict", [first, conflicting], created_at="2026-07-10T00:00:00Z"
        )
        duplicates = next(check for check in report["checks"] if check["code"] == "duplicates")
        self.assertEqual(duplicates["count"], 1)
        self.assertTrue(report["quarantine"])

    def test_irregular_trades_do_not_use_bar_interval_policy(self) -> None:
        def trade(timestamp: int, sequence: int) -> CanonicalEvent:
            return CanonicalEvent.from_raw(
                raw={"timestamp": timestamp, "sequence": sequence},
                source="fixture",
                venue="test",
                asset_class="synthetic",
                instrument_id="TEST",
                event_type=EventType.TRADE,
                event_time_ns=timestamp,
                receive_time_ns=timestamp + 1,
                ingest_id=f"trade-{sequence}",
                sequence=sequence,
                payload={"price": Decimal("100"), "size": Decimal("1")},
            )

        report = build_quality_report(
            "trades",
            [trade(100, 1), trade(10_000, 2)],
            policy=QualityPolicy(expected_interval_ns=100),
            created_at="2026-07-10T00:00:00Z",
        )
        missing = next(check for check in report["checks"] if check["code"] == "missing_intervals")
        self.assertEqual(missing["count"], 0)

    def test_crossed_book_is_critical(self) -> None:
        event = CanonicalEvent.from_raw(
            raw={"book": 1},
            source="fixture",
            venue="test",
            asset_class="prediction_market",
            instrument_id="OUTCOME",
            event_type=EventType.BOOK_SNAPSHOT,
            event_time_ns=1,
            receive_time_ns=2,
            ingest_id="book",
            payload={"bids": [[Decimal("0.60"), Decimal("1")]], "asks": [[Decimal("0.59"), Decimal("1")]]},
        )
        report = build_quality_report("book", [event], created_at="2026-07-10T00:00:00Z")
        crossed = next(check for check in report["checks"] if check["code"] == "crossed_book")
        self.assertEqual(crossed["count"], 1)
        self.assertEqual(report["promotion_impact"], "blocked")

    def test_receive_time_inversion_blocks_quality(self) -> None:
        first = bar(100, "100", sequence=1, receive_offset=200)
        second = bar(200, "101", sequence=2, receive_offset=1)
        report = build_quality_report(
            "receive-inversion",
            [first, second],
            created_at="2026-07-10T00:00:00Z",
        )
        check = next(
            item
            for item in report["checks"]
            if item["code"] == "receive_time_inversion"
        )
        self.assertEqual(check["count"], 1)
        self.assertEqual(report["promotion_impact"], "blocked")


class AdapterContractTests(unittest.TestCase):
    def test_binance_fixture_normalizes_losslessly(self) -> None:
        client = FakePublicClient({})
        adapter = BinanceSpotAdapter(client=client)  # type: ignore[arg-type]
        raw = [[1704067200000, "42000.10", "42100", "41900", "42050.25", "12.5", 1704067259999, "525000", 42]]
        events = adapter.normalize(raw, FetchRequest(kind="klines", instrument_id="BTCUSDT"), receive_time_ns=1704067260000000000)
        self.assertIsInstance(adapter, ReadOnlyAdapter)
        self.assertEqual(events[0].payload["close"], Decimal("42050.25"))
        self.assertEqual(events[0].receive_time_ns, 1704067260000000000)
        self.assertEqual(events[0].payload["close_time_ns"], 1704067259999000000)
        self.assertEqual(adapter.capabilities.maximum_promotion_mode, "diagnostic")

    def test_binance_excludes_unclosed_candle_and_keeps_receive_time(self) -> None:
        adapter = BinanceSpotAdapter(client=FakePublicClient({}))  # type: ignore[arg-type]
        receive_time_ns = 120_000_000_000
        events = adapter.normalize(
            [binance_kline(0), binance_kline(120_000)],
            FetchRequest(kind="klines", instrument_id="BTCUSDT"),
            receive_time_ns=receive_time_ns,
        )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].receive_time_ns, receive_time_ns)

    def test_binance_half_open_chunks_and_refetches_are_stable(self) -> None:
        client = BinanceWindowClient([binance_kline(0), binance_kline(60_000)])
        adapter = BinanceSpotAdapter(client=client)  # type: ignore[arg-type]
        first_request = FetchRequest(
            kind="klines",
            instrument_id="BTCUSDT",
            start_ns=0,
            end_ns=60_000_000_000,
            limit=2,
        )
        second_request = FetchRequest(
            kind="klines",
            instrument_id="BTCUSDT",
            start_ns=60_000_000_000,
            end_ns=120_000_000_000,
            limit=2,
        )
        first_raw = adapter.fetch_raw(first_request)
        second_raw = adapter.fetch_raw(second_request)
        first = adapter.normalize(first_raw, first_request, receive_time_ns=200_000_000_000)
        second = adapter.normalize(second_raw, second_request, receive_time_ns=200_000_000_000)
        refetched = adapter.normalize(
            adapter.fetch_raw(first_request),
            first_request,
            receive_time_ns=200_000_000_000,
        )
        self.assertEqual(client.calls[0]["endTime"], 59_999)
        self.assertEqual(len({event.ingest_id for event in [*first, *second]}), 2)
        self.assertEqual(first, refetched)

    def test_binance_fetch_paginates_until_short_page(self) -> None:
        client = BinanceWindowClient(
            [
                binance_kline(0),
                binance_kline(60_000),
                binance_kline(120_000),
            ]
        )
        adapter = BinanceSpotAdapter(client=client)  # type: ignore[arg-type]
        rows = adapter.fetch_raw(
            FetchRequest(
                kind="klines",
                instrument_id="BTCUSDT",
                start_ns=0,
                end_ns=180_000_000_000,
                limit=2,
            )
        )
        self.assertEqual([row[0] for row in rows], [0, 60_000, 120_000])
        self.assertEqual(len(client.calls), 2)

    def test_polymarket_dynamic_fee_and_book_normalization(self) -> None:
        fee_url = f"{PolymarketAdapter.clob_base}/fee-rate/token-yes"
        client = FakePublicClient({fee_url: {"base_fee": 120}})
        adapter = PolymarketAdapter(client=client)  # type: ignore[arg-type]
        raw = {
            "market": "condition",
            "asset_id": "token-yes",
            "timestamp": "1704067200000",
            "hash": "abc",
            "bids": [{"price": "0.45", "size": "10"}],
            "asks": [{"price": "0.55", "size": "12"}],
        }
        event = adapter.normalize(raw, FetchRequest(kind="book", instrument_id="token-yes"), receive_time_ns=1704067201000000000)[0]
        snapshot = adapter.cost_snapshot("token-yes", observed_at_ns=1704067201000000000)
        self.assertEqual(event.payload["bids"], [["0.45", "10"]])
        self.assertEqual(snapshot["fee_rate"], "120")
        self.assertTrue(snapshot["dynamic"])
        self.assertIsNone(client.calls[0][1])

    def test_polymarket_rejects_seconds_and_microseconds_timestamps(self) -> None:
        adapter = PolymarketAdapter(client=FakePublicClient({}))  # type: ignore[arg-type]
        request = FetchRequest(kind="book", instrument_id="token-yes")
        for timestamp in ("1704067200", "1704067200000000"):
            with self.subTest(timestamp=timestamp), self.assertRaisesRegex(
                ValueError, "timestamp units"
            ):
                adapter.normalize(
                    {"timestamp": timestamp, "bids": [], "asks": []},
                    request,
                    receive_time_ns=1_704_067_201_000_000_000,
                )

    def test_futures_fixture_replay_and_path_boundary(self) -> None:
        adapter = DatabentoCompatibleFuturesAdapter(FUTURES_FIXTURE)
        instruments = adapter.discover_instruments()
        raw = adapter.fetch_raw(FetchRequest(kind="bars"))
        events = adapter.normalize(raw, FetchRequest(kind="bars"), receive_time_ns=1)
        self.assertEqual(instruments[0].multiplier, Decimal("50"))
        self.assertEqual(len(events), 2)
        self.assertEqual(adapter.capabilities.maximum_promotion_mode, "diagnostic")
        with self.assertRaises(ValueError):
            adapter.fetch_raw(FetchRequest(kind="bars", parameters={"fixture": "../../outside.json"}))

    def test_futures_volume_roll_keeps_concrete_execution_contract(self) -> None:
        events = []
        fixtures = (
            (100, "5000", "5010", "10", "5"),
            (200, "5002", "5012", "4", "12"),
            (300, "5005", "5015", "3", "13"),
        )
        for timestamp, old_close, new_close, front_volume, back_volume in fixtures:
            for contract, close, volume in (("ESU6", old_close, front_volume), ("ESZ6", new_close, back_volume)):
                events.append(
                    CanonicalEvent.from_raw(
                        raw={"contract": contract, "timestamp": timestamp},
                        source="fixture",
                        venue="XCME",
                        asset_class="futures",
                        instrument_id=contract,
                        event_type=EventType.BAR,
                        event_time_ns=timestamp,
                        receive_time_ns=timestamp + 1,
                        ingest_id=f"{contract}-{timestamp}",
                        payload={"close": Decimal(close), "volume": Decimal(volume)},
                    )
                )
        rows = build_volume_rolled_series(events)
        self.assertEqual([row["execution_instrument_id"] for row in rows], ["ESU6", "ESU6", "ESZ6"])
        self.assertFalse(rows[0]["rolled"])
        self.assertTrue(rows[2]["rolled"])
        self.assertEqual(rows[2]["roll_adjustment"], "-10")
        self.assertEqual(rows[2]["signal_close"], "5005")

    def test_futures_volume_roll_hysteresis_ignores_flip_flops(self) -> None:
        events = []
        volumes = ((100, "10", "5"), (200, "4", "12"), (300, "11", "6"), (400, "3", "13"))
        for timestamp, front_volume, back_volume in volumes:
            for contract, volume in (("ESU6", front_volume), ("ESZ6", back_volume)):
                events.append(
                    CanonicalEvent.from_raw(
                        raw={"contract": contract, "timestamp": timestamp},
                        source="fixture",
                        venue="XCME",
                        asset_class="futures",
                        instrument_id=contract,
                        event_type=EventType.BAR,
                        event_time_ns=timestamp,
                        receive_time_ns=timestamp + 1,
                        ingest_id=f"flip-{contract}-{timestamp}",
                        payload={"close": Decimal("5000"), "volume": Decimal(volume)},
                    )
                )
        rows = build_volume_rolled_series(events)
        self.assertEqual(
            [row["execution_instrument_id"] for row in rows],
            ["ESU6", "ESU6", "ESU6", "ESU6"],
        )
        self.assertFalse(any(row["rolled"] for row in rows))

    def test_futures_volume_roll_ties_retain_incumbent_and_reset_streak(self) -> None:
        events = []
        volumes = (
            (100, "10", "5"),
            (200, "4", "12"),
            (300, "8", "8"),
            (400, "4", "12"),
        )
        for timestamp, front_volume, back_volume in volumes:
            for contract, volume in (
                ("ESU6", front_volume),
                ("ESZ6", back_volume),
            ):
                events.append(
                    CanonicalEvent.from_raw(
                        raw={"contract": contract, "timestamp": timestamp},
                        source="fixture",
                        venue="XCME",
                        asset_class="futures",
                        instrument_id=contract,
                        event_type=EventType.BAR,
                        event_time_ns=timestamp,
                        receive_time_ns=timestamp + 1,
                        ingest_id=f"tie-{contract}-{timestamp}",
                        payload={
                            "close": Decimal("5000"),
                            "volume": Decimal(volume),
                        },
                    )
                )
        rows = build_volume_rolled_series(events)
        self.assertEqual(
            [row["execution_instrument_id"] for row in rows],
            ["ESU6", "ESU6", "ESU6", "ESU6"],
        )
        self.assertFalse(any(row["rolled"] for row in rows))

    def test_futures_volume_roll_names_missing_incumbent_before_switch(self) -> None:
        events = []
        for timestamp, contracts in (
            (100, (("ESU6", "10"), ("ESZ6", "5"))),
            (200, (("ESZ6", "12"),)),
        ):
            for contract, volume in contracts:
                events.append(
                    CanonicalEvent.from_raw(
                        raw={"contract": contract, "timestamp": timestamp},
                        source="fixture",
                        venue="XCME",
                        asset_class="futures",
                        instrument_id=contract,
                        event_type=EventType.BAR,
                        event_time_ns=timestamp,
                        receive_time_ns=timestamp + 1,
                        ingest_id=f"missing-{contract}-{timestamp}",
                        payload={
                            "close": Decimal("5000"),
                            "volume": Decimal(volume),
                        },
                    )
                )
        with self.assertRaisesRegex(
            ValueError,
            r"incumbent contract ESU6 missing while challenger ESZ6.*timestamp 200",
        ):
            build_volume_rolled_series(events, persistence_bars=1)

    def test_polymarket_book_hash_gap_requires_resync(self) -> None:
        snapshot = CanonicalEvent.from_raw(
            raw={"snapshot": 1},
            source="fixture",
            venue="polymarket",
            asset_class="prediction_market",
            instrument_id="YES",
            event_type=EventType.BOOK_SNAPSHOT,
            event_time_ns=1,
            receive_time_ns=2,
            ingest_id="snapshot",
            sequence=10,
            payload={"hash": "h1", "bids": [["0.4", "10"]], "asks": [["0.6", "10"]]},
        )
        bad_delta = CanonicalEvent.from_raw(
            raw={"delta": 1},
            source="fixture",
            venue="polymarket",
            asset_class="prediction_market",
            instrument_id="YES",
            event_type=EventType.BOOK_DELTA,
            event_time_ns=3,
            receive_time_ns=4,
            ingest_id="delta",
            sequence=12,
            payload={"previous_hash": "wrong", "hash": "h2", "changes": []},
        )
        state = PolymarketBookState("YES")
        state.apply_snapshot(snapshot)
        self.assertFalse(state.apply_delta(bad_delta))
        self.assertTrue(state.resync_required)


class ParquetStoreTests(unittest.TestCase):
    def test_partition_is_immutable(self) -> None:
        try:
            import pyarrow  # noqa: F401
        except ImportError:
            self.skipTest("pyarrow is provided by the data extra")
        with tempfile.TemporaryDirectory() as tmp:
            store = ImmutableParquetStore(Path(tmp))
            event = bar(1_704_067_200_000_000_000, "100.25", sequence=1)
            path, fingerprint = store.commit(
                [event], source="fixture", venue="test", instrument="TEST", date="2024-01-01"
            )
            self.assertTrue((path / "events.parquet").is_file())
            self.assertEqual((path / "fingerprint.sha256").read_text(encoding="ascii").strip(), fingerprint)
            self.assertEqual(fingerprint, stable_fingerprint([event.as_dict()]))
            with self.assertRaises(PartitionExistsError):
                store.commit([event], source="fixture", venue="test", instrument="TEST", date="2024-01-01")
            try:
                import duckdb  # noqa: F401
            except ImportError:
                pass
            else:
                rows = DuckDBQueryLayer().scan(
                    [path / "events.parquet"],
                    columns=("instrument_id", "event_type"),
                    where="instrument_id = ?",
                    parameters=("TEST",),
                )
                self.assertEqual(rows, [{"instrument_id": "TEST", "event_type": "bar"}])

    def test_raw_archive_is_immutable_and_unlock_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            archive = RawResponseArchive(Path(tmp))
            first_path, first_hash = archive.store(
                provider="fixture", stream="rest", received_at_ns=1, payload={"price": "1.23"}
            )
            second_path, second_hash = archive.store(
                provider="fixture", stream="rest", received_at_ns=1, payload={"price": "1.23"}
            )
            self.assertEqual((first_path, first_hash), (second_path, second_hash))
            self.assertEqual(first_path.read_text(encoding="utf-8"), '{"price":"1.23"}\n')
            research_adapter = BinanceSpotAdapter(archive=archive, license_reviewed=True)
            diagnostic_adapter = BinanceSpotAdapter(archive=archive, license_reviewed=False)
            self.assertEqual(research_adapter.capabilities.maximum_promotion_mode, "research")
            self.assertTrue(research_adapter.capabilities.replay)
            self.assertEqual(diagnostic_adapter.capabilities.maximum_promotion_mode, "diagnostic")


class DataCliTests(unittest.TestCase):
    def test_quality_and_features_commands_have_stable_envelopes(self) -> None:
        first = bar(1_704_067_200_000_000_000, "100", sequence=1)
        second = bar(1_704_067_260_000_000_000, "101", sequence=2)
        dataset_fingerprint = stable_fingerprint([first.as_dict(), second.as_dict()])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            events_path = root / "events.jsonl"
            events_path.write_text(
                "\n".join(json.dumps(event.as_dict(), sort_keys=True) for event in (first, second)) + "\n",
                encoding="utf-8",
            )
            quality_path = root / "quality_report.json"
            config_path = root / "config.json"
            config_path.write_text('{"window": 1}', encoding="utf-8")
            with redirect_stdout(io.StringIO()) as quality_output:
                quality_exit = cli_main(
                    [
                        "data",
                        "quality",
                        str(events_path),
                        "--dataset-id",
                        "fixture",
                        "--created-at",
                        "2026-07-10T00:00:00Z",
                        "--output",
                        str(quality_path),
                        "--format",
                        "json",
                    ]
                )
            with redirect_stdout(io.StringIO()) as feature_output:
                feature_exit = cli_main(
                    [
                        "features",
                        "build",
                        str(events_path),
                        "--dataset-fingerprint",
                        dataset_fingerprint,
                        "--code-version",
                        "test",
                        "--config",
                        str(config_path),
                        "--created-at",
                        "2026-07-10T00:00:00Z",
                        "--output-dir",
                        str(root / "features"),
                        "--format",
                        "json",
                    ]
                )
            self.assertEqual(quality_exit, 0)
            self.assertEqual(feature_exit, 0)
            self.assertTrue(json.loads(quality_output.getvalue())["ok"])
            self.assertEqual(json.loads(feature_output.getvalue())["status"], "complete")
            self.assertTrue(validate_artifact(quality_path, artifact_type="quality_report").ok)
            self.assertTrue(validate_artifact(root / "features" / "feature_manifest.json", artifact_type="feature_manifest").ok)


if __name__ == "__main__":
    unittest.main()

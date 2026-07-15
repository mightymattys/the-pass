from __future__ import annotations

import json
import io
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable
from contextlib import redirect_stdout

from the_pass.adapters.base import AdapterCapabilities, FetchRequest, manifest_for_events
from the_pass.cli import main as cli_main
from the_pass.data.contracts import CanonicalEvent, EventType, stable_fingerprint
from the_pass.data.ingest import (
    BundleExistsError,
    OfflineIngestService,
    validate_ingest_bundle,
)
from the_pass.validator import validate_artifact


FIXED_RECEIVE_TIME_NS = 1_704_067_300_000_000_000


class FakeAdapter:
    adapter_id = "offline-fixture"
    capabilities = AdapterCapabilities(
        event_types=("bar",),
        historical_read=True,
        live_read=False,
        authentication="none",
        replay=True,
        timestamp_quality="fixture event time",
        license_mode="synthetic fixture",
        maximum_promotion_mode="diagnostic",
    )

    def __init__(self, raw: list[dict[str, Any]], *, fail_manifest: bool = False) -> None:
        self.raw = raw
        self.fail_manifest = fail_manifest
        self.fetch_calls = 0
        self.normalize_receive_time_ns: int | None = None
        self.manifest_raw_path: Path | None = None

    def fetch_raw(self, request: FetchRequest) -> Any:
        self.fetch_calls += 1
        return self.raw

    def normalize(
        self,
        raw: Any,
        request: FetchRequest,
        *,
        receive_time_ns: int,
    ) -> list[CanonicalEvent]:
        self.normalize_receive_time_ns = receive_time_ns
        return [
            CanonicalEvent.from_raw(
                raw=row,
                source=self.adapter_id,
                venue="fixture",
                asset_class="synthetic",
                instrument_id=request.instrument_id or "TEST",
                event_type=EventType.BAR,
                event_time_ns=int(row["event_time_ns"]),
                receive_time_ns=receive_time_ns,
                ingest_id=f"fixture-{row['event_time_ns']}",
                sequence=int(row["sequence"]),
                payload={
                    "open": Decimal(row["close"]),
                    "high": Decimal(row["close"]),
                    "low": Decimal(row["close"]),
                    "close": Decimal(row["close"]),
                    "volume": Decimal("1"),
                },
            )
            for row in raw
        ]

    def build_manifest(
        self,
        events: Iterable[CanonicalEvent],
        *,
        raw_path: Path,
        quality_report: dict[str, Any],
    ) -> dict[str, Any]:
        if self.fail_manifest:
            raise RuntimeError("manifest failed")
        self.manifest_raw_path = raw_path
        return manifest_for_events(
            self.adapter_id,
            events,
            raw_path=raw_path,
            quality_report=quality_report,
            endpoint="in-memory fixture",
            license_note="synthetic test data",
        )

    def cost_snapshot(self, instrument_id: str, *, observed_at_ns: int) -> dict[str, Any]:
        return {
            "status": "fixture",
            "instrument_id": instrument_id,
            "observed_at_ns": observed_at_ns,
            "fee_rate": "0",
        }


def fixture_rows(close: str = "100") -> list[dict[str, Any]]:
    return [
        {"event_time_ns": 1_704_067_200_000_000_000, "sequence": 1, "close": close},
        {"event_time_ns": 1_704_067_260_000_000_000, "sequence": 2, "close": "101"},
    ]


class OfflineIngestServiceTests(unittest.TestCase):
    def test_bundle_rejects_schema_invalid_rehashed_quality_evidence(self) -> None:
        adapter = FakeAdapter(fixture_rows())
        service = OfflineIngestService(clock_ns=lambda: FIXED_RECEIVE_TIME_NS)
        request = FetchRequest(kind="bars", instrument_id="TEST")
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "bundle"
            service.ingest(adapter, request, output)
            quality_path = output / "quality-report.json"
            quality = json.loads(quality_path.read_text(encoding="utf-8"))
            quality.pop("summary")
            quality_path.write_text(json.dumps(quality), encoding="utf-8")
            receipt_path = output / "ingest-receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["quality_report_fingerprint"] = stable_fingerprint(quality)
            receipt_core = {
                key: value for key, value in receipt.items() if key != "receipt_fingerprint"
            }
            receipt["receipt_fingerprint"] = stable_fingerprint(receipt_core)
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            (output / "COMMITTED").write_text(
                receipt["receipt_fingerprint"] + "\n", encoding="ascii"
            )
            with self.assertRaisesRegex(ValueError, "quality report does not validate"):
                validate_ingest_bundle(output)

    def test_cli_futures_ingest_and_network_opt_in_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            request = root / "request.json"
            request.write_text(
                json.dumps(
                    {
                        "kind": "bars",
                        "instrument_id": "ESZ6",
                        "parameters": {"fixture": "events.json"},
                    }
                ),
                encoding="utf-8",
            )
            with redirect_stdout(io.StringIO()) as stdout:
                exit_code = cli_main(
                    [
                        "data",
                        "ingest",
                        "--provider",
                        "futures",
                        "--archive-root",
                        str(Path(__file__).parent / "fixtures" / "futures"),
                        "--request",
                        str(request),
                        "--output",
                        str(root / "bundle"),
                        "--format",
                        "json",
                    ]
                )
            self.assertEqual(exit_code, 0, stdout.getvalue())
            self.assertTrue((root / "bundle" / "COMMITTED").is_file())
            with redirect_stdout(io.StringIO()) as blocked_stdout:
                blocked = cli_main(
                    [
                        "data",
                        "ingest",
                        "--provider",
                        "binance",
                        "--request",
                        str(request),
                        "--output",
                        str(root / "network"),
                        "--format",
                        "json",
                    ]
                )
            self.assertEqual(blocked, 3)
            self.assertEqual(json.loads(blocked_stdout.getvalue())["status"], "forbidden")

    def test_fake_adapter_commits_complete_valid_bundle_without_network(self) -> None:
        adapter = FakeAdapter(fixture_rows())
        service = OfflineIngestService(clock_ns=lambda: FIXED_RECEIVE_TIME_NS)
        request = FetchRequest(kind="bars", instrument_id="TEST")

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "bundle"
            result = service.ingest(adapter, request, output)

            self.assertEqual(adapter.fetch_calls, 1)
            self.assertEqual(adapter.normalize_receive_time_ns, FIXED_RECEIVE_TIME_NS)
            self.assertEqual(adapter.manifest_raw_path, Path("raw/response.json"))
            self.assertEqual(
                {path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()},
                {
                    "raw/response.json",
                    "canonical-events.jsonl",
                    "quality-report.json",
                    "data-manifest.json",
                    "request.json",
                    "ingest-receipt.json",
                    "COMMITTED",
                },
            )
            self.assertEqual(json.loads(result.raw_path.read_text(encoding="utf-8")), fixture_rows())
            canonical_rows = [
                json.loads(line)
                for line in result.canonical_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(result.canonical_fingerprint, stable_fingerprint(canonical_rows))
            self.assertEqual(result.data_manifest["source"]["raw_path"], "raw/response.json")
            self.assertEqual(
                result.data_manifest["source"]["normalized_path"],
                "canonical-events.jsonl",
            )
            self.assertTrue(validate_artifact(result.quality_path, artifact_type="quality_report").ok)
            self.assertTrue(validate_artifact(result.manifest_path, artifact_type="data_manifest").ok)
            receipt = json.loads(result.receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["event_count"], 2)
            self.assertEqual(receipt["cross_check"]["status"], "not_performed")
            self.assertEqual(
                result.committed_path.read_text(encoding="ascii").strip(),
                receipt["receipt_fingerprint"],
            )

    def test_existing_bundle_is_preserved_without_fetching(self) -> None:
        adapter = FakeAdapter(fixture_rows())
        service = OfflineIngestService(clock_ns=lambda: FIXED_RECEIVE_TIME_NS)

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "bundle"
            output.mkdir()
            marker = output / "keep.txt"
            marker.write_text("unchanged", encoding="utf-8")

            with self.assertRaises(BundleExistsError):
                service.ingest(adapter, FetchRequest(kind="bars", instrument_id="TEST"), output)

            self.assertEqual(adapter.fetch_calls, 0)
            self.assertEqual(marker.read_text(encoding="utf-8"), "unchanged")

    def test_existing_broken_symlink_is_treated_as_an_occupied_output(self) -> None:
        adapter = FakeAdapter(fixture_rows())
        service = OfflineIngestService(clock_ns=lambda: FIXED_RECEIVE_TIME_NS)

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "bundle"
            output.symlink_to(Path(tmp) / "missing-target", target_is_directory=True)

            with self.assertRaises(BundleExistsError):
                service.ingest(adapter, FetchRequest(kind="bars", instrument_id="TEST"), output)

            self.assertEqual(adapter.fetch_calls, 0)
            self.assertTrue(output.is_symlink())

    def test_failed_build_does_not_publish_partial_bundle(self) -> None:
        adapter = FakeAdapter(fixture_rows(), fail_manifest=True)
        service = OfflineIngestService(clock_ns=lambda: FIXED_RECEIVE_TIME_NS)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = root / "bundle"
            with self.assertRaisesRegex(RuntimeError, "manifest failed"):
                service.ingest(adapter, FetchRequest(kind="bars", instrument_id="TEST"), output)

            self.assertFalse(output.exists())
            self.assertEqual(list(root.glob(".bundle.staging-*")), [])


if __name__ == "__main__":
    unittest.main()

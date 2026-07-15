from __future__ import annotations

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from the_pass.adapters.base import AdapterCapabilities, FetchRequest, manifest_for_events
from the_pass.data.contracts import CanonicalEvent, EventType
from the_pass.data.dataset import build_dataset, build_dataset_plan, validate_dataset_plan
from the_pass.validator import validate_artifact


class ChunkAdapter:
    adapter_id = "offline-fixture"
    capabilities = AdapterCapabilities(
        event_types=("bar",),
        historical_read=True,
        live_read=False,
        authentication="none",
        replay=True,
        timestamp_quality="fixture nanoseconds",
        license_mode="synthetic fixture",
        maximum_promotion_mode="research",
    )

    def __init__(
        self,
        *,
        fail_call: int | None = None,
        conflicting: bool = False,
        duplicate_identical: bool = False,
    ) -> None:
        self.fetch_calls = 0
        self.fail_call = fail_call
        self.conflicting = conflicting
        self.duplicate_identical = duplicate_identical

    def fetch_raw(self, request: FetchRequest) -> Any:
        self.fetch_calls += 1
        if self.fetch_calls == self.fail_call:
            raise RuntimeError("fixture interruption")
        event_time = (
            1_000 if self.conflicting or self.duplicate_identical else request.start_ns
        )
        return {
            "event_time_ns": event_time,
            "close": str(
                100
                if self.duplicate_identical
                else request.start_ns
                if self.conflicting
                else 100 + self.fetch_calls
            ),
        }

    def normalize(
        self, raw: Any, request: FetchRequest, *, receive_time_ns: int
    ) -> list[CanonicalEvent]:
        event_time = int(raw["event_time_ns"])
        return [
            CanonicalEvent.from_raw(
                raw=raw,
                source=self.adapter_id,
                venue="fixture",
                asset_class="synthetic",
                instrument_id=request.instrument_id or "TEST",
                event_type=EventType.BAR,
                event_time_ns=event_time,
                receive_time_ns=max(receive_time_ns, event_time),
                ingest_id=f"fixture-{event_time}",
                sequence=event_time // 1_000,
                payload={
                    "open": Decimal(raw["close"]),
                    "high": Decimal(raw["close"]),
                    "low": Decimal(raw["close"]),
                    "close": Decimal(raw["close"]),
                    "volume": Decimal(1),
                },
            )
        ]

    def cross_check(
        self, primary: Iterable[CanonicalEvent], reference: Any
    ) -> dict[str, Any]:
        return {"status": "pass" if reference == {"ok": True} else "warning"}

    def build_manifest(
        self,
        events: Iterable[CanonicalEvent],
        *,
        raw_path: Path,
        quality_report: dict[str, Any],
    ) -> dict[str, Any]:
        return manifest_for_events(
            self.adapter_id,
            events,
            raw_path=raw_path,
            quality_report=quality_report,
            endpoint="fixture",
            license_note="synthetic",
        )

    def cost_snapshot(
        self, instrument_id: str, *, observed_at_ns: int
    ) -> dict[str, Any]:
        return {"status": "fixture", "instrument_id": instrument_id}


def plan(*, cross_check_required: bool = False) -> dict[str, Any]:
    return build_dataset_plan(
        plan_id="fixture-dataset",
        provider="offline-fixture",
        kind="bars",
        instrument_id="TEST",
        start_ns=1_000,
        end_ns=4_000,
        chunk_ns=1_000,
        expected_interval_ns=1_000,
        created_at="2026-07-15T00:00:00Z",
        cross_check_required=cross_check_required,
    )


class DatasetBuildTests(unittest.TestCase):
    def test_plan_is_exact_contiguous_and_fingerprinted(self) -> None:
        document = validate_dataset_plan(plan())
        self.assertEqual(len(document["requests"]), 3)
        intervals = [
            (item["request"]["start_ns"], item["request"]["end_ns"])
            for item in document["requests"]
        ]
        self.assertEqual(intervals, [(1_000, 2_000), (2_000, 3_000), (3_000, 4_000)])

    def test_interrupted_build_resumes_committed_chunks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "dataset"
            with self.assertRaisesRegex(RuntimeError, "fixture interruption"):
                build_dataset(
                    ChunkAdapter(fail_call=2),
                    plan(),
                    output,
                    clock_ns=lambda: 10_000,
                )
            self.assertTrue((output / "chunks" / "chunk-000000" / "COMMITTED").is_file())
            resumed_adapter = ChunkAdapter()
            result = build_dataset(
                resumed_adapter, plan(), output, clock_ns=lambda: 10_000
            )
            self.assertEqual((result.resumed_chunks, result.fetched_chunks), (1, 2))
            self.assertEqual(resumed_adapter.fetch_calls, 2)
            self.assertEqual(result.event_count, 3)
            self.assertTrue(result.committed_path.is_file())
            self.assertTrue(validate_artifact(result.receipt_path, artifact_type="dataset_receipt").ok)

    def test_changed_chunk_receipt_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "dataset"
            with self.assertRaises(RuntimeError):
                build_dataset(
                    ChunkAdapter(fail_call=2), plan(), output, clock_ns=lambda: 10_000
                )
            receipt_path = output / "chunks" / "chunk-000000" / "ingest-receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["event_count"] = 99
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "receipt fingerprint"):
                build_dataset(ChunkAdapter(), plan(), output, clock_ns=lambda: 10_000)

    def test_conflicting_duplicate_blocks_publication(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "dataset"
            with self.assertRaisesRegex(ValueError, "conflicting duplicate"):
                build_dataset(
                    ChunkAdapter(conflicting=True),
                    plan(),
                    output,
                    clock_ns=lambda: 10_000,
                )
            self.assertFalse((output / "COMMITTED").exists())

    def test_identical_duplicates_deduplicate_and_clean_builds_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            first = build_dataset(
                ChunkAdapter(duplicate_identical=True),
                plan(),
                Path(tmp) / "first",
                clock_ns=lambda: 10_000,
            )
            second = build_dataset(
                ChunkAdapter(duplicate_identical=True),
                plan(),
                Path(tmp) / "second",
                clock_ns=lambda: 10_000,
            )
            self.assertEqual(first.event_count, 1)
            self.assertEqual(first.dataset_fingerprint, second.dataset_fingerprint)

    def test_required_cross_check_blocks_until_every_chunk_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            document = plan(cross_check_required=True)
            result = build_dataset(
                ChunkAdapter(), document, Path(tmp) / "dataset", clock_ns=lambda: 10_000
            )
            self.assertEqual(result.promotion_impact, "blocked")

        with tempfile.TemporaryDirectory() as tmp:
            document = plan(cross_check_required=True)
            references = {
                item["chunk_id"]: {"ok": True} for item in document["requests"]
            }
            result = build_dataset(
                ChunkAdapter(),
                document,
                Path(tmp) / "dataset",
                cross_check_references=references,
                clock_ns=lambda: 10_000,
            )
            self.assertEqual(result.promotion_impact, "none")

    def test_committed_dataset_is_fully_revalidated_on_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "dataset"
            build_dataset(ChunkAdapter(), plan(), output, clock_ns=lambda: 10_000)
            events_path = output / "canonical-events.jsonl"
            events_path.write_bytes(events_path.read_bytes() + b"{}\n")

            with self.assertRaisesRegex(ValueError, "canonical events are invalid"):
                build_dataset(ChunkAdapter(), plan(), output, clock_ns=lambda: 10_000)


if __name__ == "__main__":
    unittest.main()

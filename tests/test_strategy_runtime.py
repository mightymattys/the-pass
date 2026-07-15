from __future__ import annotations

import os
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout

from the_pass.cli import main as cli_main
from the_pass.adapters.base import manifest_for_events
from the_pass.audit import ReproductionError, reproduce_package
from the_pass.data.contracts import CanonicalEvent, EventType, stable_fingerprint
from the_pass.data.quality import QualityPolicy, build_quality_report
from the_pass.engine.baselines import generate_synthetic_bars
from the_pass.engine.package import strategy_spec
from the_pass.robustness import run_strategy_sweep
from the_pass.validator import validate_package
from the_pass.strategy_runtime import (
    StrategyRuntimeError,
    load_execution_config,
    parse_execution_config,
    parse_strategy_descriptor,
    run_strategy,
)


VALID_STRATEGY = """
from decimal import Decimal

from the_pass.engine.contracts import SimulatedIntent


class Strategy:
    strategy_id = "fixture_strategy_v1"

    def __init__(self, quantity):
        self.quantity = Decimal(quantity)

    def on_event(self, event, context):
        if context.event_index != 0:
            return []
        return [
            SimulatedIntent(
                intent_id="fixture-intent-1",
                instrument_id=event.instrument_id,
                side="buy",
                quantity=self.quantity,
                decision_time_ns=context.decision_time_ns,
                intent_type="bar",
            )
        ]


def build_strategy(config):
    return Strategy(config["quantity"])
"""


def canonical_bars() -> list:
    return [
        CanonicalEvent.from_raw(
            raw={"row": index},
            source="fixture",
            venue="offline",
            asset_class="crypto_spot",
            instrument_id="BTCUSDT",
            event_type=EventType.BAR,
            event_time_ns=index,
            receive_time_ns=index,
            ingest_id=f"bar-{index}",
            sequence=index,
            payload={
                "open": str(100 + index),
                "high": str(101 + index),
                "low": str(99 + index),
                "close": str(100 + index),
                "volume": "10",
            },
        )
        for index in (1, 2)
    ]


class StrategyRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "strategy.py").write_text(VALID_STRATEGY, encoding="utf-8")
        self.descriptor = {
            "schema_version": 1,
            "strategy_id": "fixture_strategy_v1",
            "strategy_file": "strategy.py",
            "factory": "build_strategy",
            "config": {"quantity": "2"},
            "asset_class": "crypto_spot",
            "owner": "research-team",
        }
        self.execution = {
            "schema_version": 1,
            "initial_cash": "10000",
            "fill_model": "bar_next_open",
            "fee_rate": "0.001",
            "slippage_bps": "5",
        }

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_custom_strategy_is_deterministic_and_fills_only_on_next_event(self) -> None:
        with patch.dict(os.environ, {"OPENAI_API_KEY": "must-not-reach-worker"}):
            first = run_strategy(
                canonical_bars(),
                descriptor=self.descriptor,
                execution=self.execution,
                workspace_root=self.root,
            )
            second = run_strategy(
                canonical_bars(),
                descriptor=self.descriptor,
                execution=self.execution,
                workspace_root=self.root,
            )

        self.assertEqual(first["result_fingerprint"], second["result_fingerprint"])
        self.assertEqual(first, second)
        self.assertEqual(len(first["fills"]), 1)
        self.assertEqual(first["fills"][0]["event_time_ns"], 2)
        self.assertFalse(first["credentials_present"])
        self.assertFalse(first["network_or_order_modules_loaded"])
        self.assertEqual(first["isolation"]["mode"], "trusted_local")
        self.assertEqual(first["isolation"]["network_enforcement"], "none")
        self.assertEqual(first["isolation"]["filesystem_enforcement"], "none")
        self.assertFalse(first["runtime_promotion_eligible"])
        self.assertEqual(first["promotion_status"], "blocked")

    def test_trusted_local_runtime_reports_host_access_truthfully(self) -> None:
        marker = self.root / "strategy-side-effect.txt"
        source = (
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('written', encoding='utf-8')\n"
            + VALID_STRATEGY
        )
        (self.root / "strategy.py").write_text(source, encoding="utf-8")
        result = run_strategy(
            canonical_bars(),
            descriptor=self.descriptor,
            execution=self.execution,
            workspace_root=self.root,
        )
        self.assertEqual(marker.read_text(encoding="utf-8"), "written")
        self.assertEqual(result["isolation"]["network_enforcement"], "none")
        self.assertEqual(result["isolation"]["filesystem_enforcement"], "none")

    def test_hardened_runtime_requires_and_verifies_launcher_attestation(self) -> None:
        with self.assertRaisesRegex(StrategyRuntimeError, "sandbox launcher"):
            run_strategy(
                canonical_bars(),
                descriptor=self.descriptor,
                execution=self.execution,
                workspace_root=self.root,
                runtime_mode="hardened",
            )

        launcher = self.root / "fixture-sandbox-launcher"
        launcher.write_text(
            "#!/usr/bin/env python3\n"
            "import json, subprocess, sys\n"
            "from pathlib import Path\n"
            "request = json.loads(Path(sys.argv[1]).read_text())\n"
            "completed = subprocess.run(request['worker_argv'], cwd=request['working_directory'])\n"
            "attestation = {\n"
            "  'schema_version': 1,\n"
            "  'launcher_sha256': request['launcher_sha256'],\n"
            "  'request_fingerprint': request['request_fingerprint'],\n"
            "  **request['requirements'],\n"
            "}\n"
            "Path(request['attestation_path']).write_text(json.dumps(attestation))\n"
            "raise SystemExit(completed.returncode)\n",
            encoding="utf-8",
        )
        launcher.chmod(0o700)
        result = run_strategy(
            canonical_bars(),
            descriptor=self.descriptor,
            execution=self.execution,
            workspace_root=self.root,
            runtime_mode="hardened",
            sandbox_launcher=launcher,
        )
        self.assertEqual(result["isolation"]["mode"], "hardened")
        self.assertEqual(result["isolation"]["network_enforcement"], "denied")
        self.assertEqual(
            result["isolation"]["filesystem_enforcement"],
            "read_only_inputs_temp_output_only",
        )
        self.assertTrue(result["runtime_promotion_eligible"])

    def test_descriptor_rejects_traversal_symlink_escape_and_credentials(self) -> None:
        outside = self.root.parent / "outside-strategy.py"
        outside.write_text(VALID_STRATEGY, encoding="utf-8")
        self.addCleanup(outside.unlink)

        traversal = dict(self.descriptor, strategy_file="../outside-strategy.py")
        with self.assertRaisesRegex(ValueError, "traversal"):
            parse_strategy_descriptor(traversal, workspace_root=self.root)

        (self.root / "escape.py").symlink_to(outside)
        escaped = dict(self.descriptor, strategy_file="escape.py")
        with self.assertRaisesRegex(ValueError, "escapes"):
            parse_strategy_descriptor(escaped, workspace_root=self.root)

        credential = dict(self.descriptor, config={"api_key": "forbidden"})
        with self.assertRaisesRegex(ValueError, "credential-like"):
            parse_strategy_descriptor(credential, workspace_root=self.root)

    def test_execution_parser_rejects_invalid_decimals_and_malformed_json(self) -> None:
        for field, value in (
            ("initial_cash", "0"),
            ("fee_rate", "-0.1"),
            ("slippage_bps", "NaN"),
        ):
            with self.subTest(field=field, value=value):
                with self.assertRaises(ValueError):
                    parse_execution_config(dict(self.execution, **{field: value}))
        with self.assertRaisesRegex(ValueError, "decimal string"):
            parse_execution_config(dict(self.execution, fee_rate=0.1))

        malformed = self.root / "execution.json"
        malformed.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "duplicate"):
            load_execution_config(malformed)

    def test_invalid_factory_and_network_import_fail_closed(self) -> None:
        cases = {
            "missing-id": "def build_strategy(config):\n    return object()\n",
            "factory-error": "def build_strategy(config):\n    raise RuntimeError('failed')\n",
            "network-import": "import socket\ndef build_strategy(config):\n    return object()\n",
            "trading-client-import": "import ccxt\ndef build_strategy(config):\n    return object()\n",
        }
        for name, source in cases.items():
            with self.subTest(name=name):
                (self.root / "strategy.py").write_text(source, encoding="utf-8")
                with self.assertRaises(StrategyRuntimeError):
                    run_strategy(
                        canonical_bars(),
                        descriptor=self.descriptor,
                        execution=self.execution,
                        workspace_root=self.root,
                    )

    def test_timeout_and_oversized_output_are_bounded_failures(self) -> None:
        (self.root / "strategy.py").write_text(
            "import time\ntime.sleep(2)\ndef build_strategy(config):\n    return object()\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(StrategyRuntimeError, "timed out") as timeout:
            run_strategy(
                canonical_bars(),
                descriptor=self.descriptor,
                execution=self.execution,
                workspace_root=self.root,
                timeout_seconds=0.1,
            )
        self.assertTrue(timeout.exception.metadata["timed_out"])

        (self.root / "strategy.py").write_text(
            'print("x" * 100000)\ndef build_strategy(config):\n    return object()\n',
            encoding="utf-8",
        )
        with self.assertRaises(StrategyRuntimeError) as oversized:
            run_strategy(
                canonical_bars(),
                descriptor=self.descriptor,
                execution=self.execution,
                workspace_root=self.root,
                output_limit_bytes=16_384,
            )
        self.assertGreaterEqual(oversized.exception.metadata["stdout_bytes"], 16_384)

    def test_generic_backtest_cli_builds_valid_deterministic_package(self) -> None:
        events = generate_synthetic_bars(instrument_id="BTCUSDT", profile="trend")
        dataset_fingerprint = stable_fingerprint([event.as_dict() for event in events])
        dataset_id = f"manifest-{dataset_fingerprint[:16]}"
        created_at = "2026-07-13T00:00:00Z"
        quality = build_quality_report(
            dataset_id,
            events,
            policy=QualityPolicy(expected_interval_ns=60_000_000_000),
            created_at=created_at,
        )
        manifest = manifest_for_events(
            "custom-fixture",
            events,
            raw_path=Path("raw/fixture.json"),
            quality_report=quality,
            endpoint="offline fixture",
            license_note="synthetic test fixture",
        )
        spec = strategy_spec(
            "fixture_strategy_v1",
            "BTCUSDT",
            "crypto_spot",
            {"variants": [self.descriptor["config"]]},
        )
        descriptor_path = self.root / "descriptor.json"
        execution_path = self.root / "execution.json"
        events_path = self.root / "events.jsonl"
        spec_path = self.root / "strategy-spec.json"
        manifest_path = self.root / "data-manifest.json"
        quality_path = self.root / "quality-report.json"
        descriptor_path.write_text(json.dumps(self.descriptor), encoding="utf-8")
        execution_path.write_text(json.dumps(self.execution), encoding="utf-8")
        events_path.write_text(
            "\n".join(json.dumps(event.as_dict(), sort_keys=True) for event in events) + "\n",
            encoding="utf-8",
        )
        for path, document in (
            (spec_path, spec),
            (manifest_path, manifest),
            (quality_path, quality),
        ):
            path.write_text(json.dumps(document), encoding="utf-8")
        output = self.root / "package"
        with redirect_stdout(io.StringIO()) as stdout:
            exit_code = cli_main(
                [
                    "backtest",
                    "run",
                    "--descriptor",
                    str(descriptor_path),
                    "--strategy-spec",
                    str(spec_path),
                    "--events",
                    str(events_path),
                    "--data-manifest",
                    str(manifest_path),
                    "--quality-report",
                    str(quality_path),
                    "--execution",
                    str(execution_path),
                    "--workspace-root",
                    str(self.root),
                    "--output",
                    str(output),
                    "--format",
                    "json",
                ]
            )
        envelope = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0, envelope)
        self.assertTrue(validate_package(output).ok)
        runtime = json.loads((output / "runtime_evidence.json").read_text(encoding="utf-8"))
        self.assertTrue(runtime["determinism_verified"])
        self.assertEqual(runtime["promotion_status"], "blocked")
        reproduction = reproduce_package(output, timeout_seconds=30)
        self.assertEqual(reproduction["status"], "pass", reproduction)
        extra = output / "reproduction" / "workspace" / "undeclared.py"
        extra.write_text("raise RuntimeError('must never load')\n", encoding="utf-8")
        with self.assertRaisesRegex(ReproductionError, "exactly match"):
            reproduce_package(output, timeout_seconds=30)
        extra.unlink()
        reproduction_spec_path = output / "reproduction_spec.json"
        reproduction_spec = json.loads(
            reproduction_spec_path.read_text(encoding="utf-8")
        )
        unsafe_spec = {**reproduction_spec, "expected_artifacts": ["../escape.json"]}
        reproduction_spec_path.write_text(json.dumps(unsafe_spec), encoding="utf-8")
        with self.assertRaisesRegex(ReproductionError, "unsafe"):
            reproduce_package(output, timeout_seconds=30)
        unknown_runner = {**reproduction_spec, "runner_id": "unknown.runner"}
        reproduction_spec_path.write_text(json.dumps(unknown_runner), encoding="utf-8")
        with self.assertRaisesRegex(ReproductionError, "tracked package is invalid"):
            reproduce_package(output, timeout_seconds=30)
        reproduction_spec_path.write_text(
            json.dumps(reproduction_spec), encoding="utf-8"
        )
        markdown_path = output / "run_report.md"
        original_markdown = markdown_path.read_text(encoding="utf-8")
        markdown_path.write_text(original_markdown + "\nchanged\n", encoding="utf-8")
        mismatch_report = reproduce_package(output, timeout_seconds=30)
        self.assertEqual(mismatch_report["status"], "blocked")
        with redirect_stdout(io.StringIO()):
            mismatch_reproduce_exit = cli_main(
                [
                    "audit",
                    "reproduce",
                    str(output),
                    "--output",
                    str(self.root / "reproduction-mismatch.json"),
                    "--format",
                    "json",
                ]
            )
        self.assertEqual(mismatch_reproduce_exit, 2)
        markdown_path.write_text(original_markdown, encoding="utf-8")
        reproduction_execution = output / "reproduction" / "execution.json"
        reproduction_execution.write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(ReproductionError, "fingerprint changed"):
            reproduce_package(output, timeout_seconds=30)

        mismatched_quality = build_quality_report(
            dataset_id,
            events[:10],
            policy=QualityPolicy(expected_interval_ns=60_000_000_000),
            created_at=created_at,
        )
        quality_path.write_text(json.dumps(mismatched_quality), encoding="utf-8")
        mismatched_output = self.root / "mismatched-package"
        with redirect_stdout(io.StringIO()) as mismatch_stdout:
            mismatch_exit = cli_main(
                [
                    "backtest",
                    "run",
                    "--descriptor",
                    str(descriptor_path),
                    "--strategy-spec",
                    str(spec_path),
                    "--events",
                    str(events_path),
                    "--data-manifest",
                    str(manifest_path),
                    "--quality-report",
                    str(quality_path),
                    "--execution",
                    str(execution_path),
                    "--workspace-root",
                    str(self.root),
                    "--output",
                    str(mismatched_output),
                    "--format",
                    "json",
                ]
            )
        self.assertEqual(mismatch_exit, 1)
        self.assertIn("QualityReport fingerprint", mismatch_stdout.getvalue())

    def test_preregistered_strategy_sweep_executes_every_cell(self) -> None:
        events = generate_synthetic_bars(instrument_id="BTCUSDT", profile="trend")
        registration = self.root / "sweep.registration.json"
        from the_pass.robustness import workflow

        original = workflow.run_strategy_verified

        def assert_registered(*args, **kwargs):
            self.assertTrue(registration.is_file())
            return original(*args, **kwargs)

        with patch(
            "the_pass.robustness.workflow.run_strategy_verified",
            side_effect=assert_registered,
        ):
            report = run_strategy_sweep(
                events,
                descriptor=self.descriptor,
                execution=self.execution,
                variants=[{"quantity": "1"}, {"quantity": "2"}],
                splits=[
                    {"start": 0, "end": 24},
                    {"start": 24, "end": 48},
                    {"start": 48, "end": 72},
                    {"start": 72, "end": 96},
                ],
                selected_index=0,
                registration_path=registration,
                workspace_root=self.root,
            )
        self.assertEqual(report["status"], "complete")
        self.assertEqual(len(report["cells"]), 8)
        self.assertEqual(report["failed_cells"], 0)
        self.assertIn("pbo", report["statistics"])
        registration_document = json.loads(registration.read_text(encoding="utf-8"))
        self.assertEqual(
            registration_document["registration_fingerprint"],
            report["registration_fingerprint"],
        )
        with patch(
            "the_pass.robustness.workflow.run_strategy_verified"
        ) as duplicate_worker:
            with self.assertRaisesRegex(FileExistsError, "create-only"):
                run_strategy_sweep(
                    events,
                    descriptor=self.descriptor,
                    execution=self.execution,
                    variants=[{"quantity": "1"}, {"quantity": "2"}],
                    splits=[
                        {"start": 0, "end": 24},
                        {"start": 24, "end": 48},
                        {"start": 48, "end": 72},
                        {"start": 72, "end": 96},
                    ],
                    selected_index=0,
                    registration_path=registration,
                    workspace_root=self.root,
                )
            duplicate_worker.assert_not_called()

        previous_source_hash = registration_document["strategy_source_sha256"]
        (self.root / "strategy.py").write_text(
            VALID_STRATEGY.replace(
                "return Strategy(config[\"quantity\"])",
                "return Strategy(str(int(config[\"quantity\"]) + 1))",
            ),
            encoding="utf-8",
        )
        changed_registration = self.root / "changed.registration.json"
        run_strategy_sweep(
            events,
            descriptor=self.descriptor,
            execution=self.execution,
            variants=[{"quantity": "1"}, {"quantity": "2"}],
            splits=[
                {"start": 0, "end": 24},
                {"start": 24, "end": 48},
                {"start": 48, "end": 72},
                {"start": 72, "end": 96},
            ],
            selected_index=0,
            registration_path=changed_registration,
            workspace_root=self.root,
        )
        changed_document = json.loads(
            changed_registration.read_text(encoding="utf-8")
        )
        self.assertNotEqual(
            previous_source_hash,
            changed_document["strategy_source_sha256"],
        )


if __name__ == "__main__":
    unittest.main()

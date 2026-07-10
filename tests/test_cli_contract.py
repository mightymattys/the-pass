from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from the_pass.cli import main as cli_main


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_KEYS = {"ok", "status", "artifact_paths", "issues", "receipt_id"}


class CliEnvelopeContractTests(unittest.TestCase):
    def invoke(self, argv: list[str]) -> tuple[int, dict]:
        stdout = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(io.StringIO()):
            exit_code = cli_main(argv)
        document = json.loads(stdout.getvalue())
        self.assertTrue(REQUIRED_KEYS <= set(document), argv)
        self.assertIsInstance(document["artifact_paths"], list)
        self.assertIsInstance(document["issues"], list)
        return exit_code, document

    def test_every_cli_group_has_a_stable_json_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = root / "missing.json"
            blocked_output = root / "backtest-output"
            blocked_output.write_text("occupied", encoding="utf-8")
            missing_package = root / "missing-package"
            invocations = {
                "validate": ["validate", str(missing), "--format", "json"],
                "validate-package": ["validate-package", str(missing_package), "--format", "json"],
                "data": [
                    "data", "quality", str(missing), "--dataset-id", "x", "--created-at",
                    "2026-07-10T00:00:00Z", "--output", str(root / "quality.json"), "--format", "json",
                ],
                "features": [
                    "features", "build", str(missing), "--dataset-fingerprint", "a" * 64,
                    "--code-version", "test", "--config", str(missing), "--created-at",
                    "2026-07-10T00:00:00Z", "--output-dir", str(root / "features"), "--format", "json",
                ],
                "screen": [
                    "screen", "run", "--closes", str(missing), "--variants", str(missing),
                    "--family", "buy_hold", "--output", str(root / "screen.json"), "--format", "json",
                ],
                "backtest": [
                    "backtest", "baseline", "--name", "buy_hold", "--output", str(blocked_output),
                    "--format", "json",
                ],
                "robustness": [
                    "robustness", "evaluate", "--matrix", str(missing), "--selected-index", "0",
                    "--output", str(root / "robustness.json"), "--format", "json",
                ],
                "risk": [
                    "risk", "build", "--returns", str(missing), "--scenarios", str(missing),
                    "--package-id", "pkg_test", "--asset-class", "crypto_intraday", "--capacity", "1",
                    "--output-dir", str(root / "risk"), "--format", "json",
                ],
                "paper": [
                    "paper", "run", "--strategy", "buy_hold", "--events", str(missing),
                    "--risk-policy", str(missing), "--observation-time-ns", "1", "--max-staleness-ns", "1",
                    "--max-clock-skew-ns", "1", "--max-outage-gap-ns", "1", "--output",
                    str(root / "paper.json"), "--format", "json",
                ],
                "automation": [
                    "automation", "run", str(missing), "--output-dir", str(root / "automation"),
                    "--scheduled-for", "2026-07-10T00:00:00Z", "--format", "json",
                ],
                "agents": [
                    "agents", "inspect", str(missing), "--format", "json",
                ],
                "incident": [
                    "incident", "create", "--id", "bad", "--severity", "P2", "--detected-at", "bad",
                    "--source", "test", "--summary", "test", "--evidence", "test", "--freeze-reason",
                    "test", "--output", str(root / "incident.json"), "--format", "json",
                ],
                "gate": [
                    "gate", "evaluate", str(missing_package), "--gate", "research_gate", "--reviewer", "x",
                    "--output", str(missing_package / "gate.json"), "--format", "json",
                ],
                "receipts": [
                    "receipts", "--format", "json", "verify", "--ledger", str(root / "missing-ledger.jsonl"),
                ],
                "workflow": [
                    "workflow", "status", "--state", str(root / "missing-state.yaml"), "--format", "json",
                ],
            }
            for group, argv in invocations.items():
                with self.subTest(group=group):
                    exit_code, document = self.invoke(argv)
                    self.assertNotEqual(exit_code, 0)
                    self.assertFalse(document["ok"])

            for group in ("report", "dashboard"):
                with self.subTest(group=group):
                    exit_code, document = self.invoke(
                        [group, "build", "--repo-root", str(ROOT), "--output-dir", str(root / group), "--format", "json"]
                    )
                    self.assertEqual(exit_code, 0)
                    self.assertTrue(document["ok"])


if __name__ == "__main__":
    unittest.main()

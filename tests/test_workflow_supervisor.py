from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from the_pass.gates import GateEvaluation
from the_pass.orchestration import new_workflow_state, write_workflow_state_atomic
from the_pass.orchestration import advance_workflow_state, read_workflow_state
from the_pass.workflow_supervisor import (
    WorkflowSupervisorError,
    _run_deterministic_stage,
    inspect_workflow_execution,
    supervise_workflow,
)


ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "tests" / "fixtures" / "fake_workflow_driver.py"


class WorkflowSupervisorTests(unittest.TestCase):
    def make_state(self, root: Path) -> Path:
        path = root / "state.yaml"
        state = new_workflow_state(
            run_id="supervisor-fixture",
            strategy_id="fixture-strategy",
            objective="Exercise the supervisor",
            target_gate="research_gate",
            strategy_owner="owner-a",
            run_owner="owner-b",
            ledger_path=root / "ledger.jsonl",
            timestamp="2026-07-11T00:00:00Z",
        )
        write_workflow_state_atomic(path, state)
        return path

    def run_driver(
        self,
        root: Path,
        mode: str,
        *,
        max_cycles: int | None = None,
        timeout_seconds: int = 5,
        max_output_bytes: int = 4_194_304,
    ):
        state = self.make_state(root)
        report = root / "supervisor.json"
        result = supervise_workflow(
            state,
            driver_argv=[sys.executable, str(DRIVER), mode],
            cwd=ROOT,
            report_path=report,
            max_cycles=max_cycles,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )
        return result, report

    def test_inspection_does_not_execute_driver(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = self.make_state(root)
            inspection = inspect_workflow_execution(
                state,
                driver_argv=[sys.executable, str(DRIVER), "blocked"],
                author_provider=None,
                available_providers=("codex", "claude"),
            )
            self.assertFalse(inspection["would_execute"])
            self.assertEqual(inspection["workflow"]["status"], "in_progress")

    def test_supervisor_runs_multiple_cycles_to_valid_kill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (result, exit_code), report_path = self.run_driver(
                Path(tmp), "two-cycle-kill"
            )
            self.assertEqual(exit_code, 2)
            self.assertEqual(result["status"], "killed")
            self.assertEqual(len(result["cycles"]), 2)
            self.assertEqual(json.loads(report_path.read_text())["status"], "killed")

    def test_supervisor_accepts_explicit_blocked_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (result, exit_code), _ = self.run_driver(Path(tmp), "blocked")
            self.assertEqual((result["status"], exit_code), ("blocked", 2))

    def test_no_progress_fails_and_records_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(WorkflowSupervisorError, "without checkpoint"):
                self.run_driver(root, "no-progress")
            report = json.loads((root / "supervisor.json").read_text())
            self.assertEqual(report["status"], "failed")

    def test_timeout_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(WorkflowSupervisorError, "timed out"):
                self.run_driver(root, "sleep", timeout_seconds=1)
            self.assertEqual(
                json.loads((root / "supervisor.json").read_text())["status"],
                "failed",
            )

    def test_output_flood_is_terminated_and_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(WorkflowSupervisorError, "output exceeded"):
                self.run_driver(root, "output-flood", max_output_bytes=1024)
            self.assertEqual(
                json.loads((root / "supervisor.json").read_text())["status"],
                "failed",
            )

    def test_illegal_skip_and_counter_jump_fail(self) -> None:
        for mode, message in (
            ("skip", "wrote invalid state"),
            ("jump", "exactly one transition"),
        ):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaisesRegex(WorkflowSupervisorError, message):
                    self.run_driver(Path(tmp), mode)

    def test_cycle_budget_exhaustion_does_not_claim_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (result, exit_code), _ = self.run_driver(
                Path(tmp), "two-cycle-kill", max_cycles=1
            )
            self.assertEqual(exit_code, 1)
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["final_workflow_status"], "in_progress")

    def test_auto_driver_executes_preflight_without_a_model_call(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = self.make_state(root)
            report, exit_code = supervise_workflow(
                state,
                driver_argv=["auto"],
                cwd=ROOT,
                report_path=root / "supervisor.json",
                max_cycles=1,
                timeout_seconds=5,
            )
            self.assertEqual(exit_code, 1)
            self.assertEqual(report["cycles"][0]["route"]["execution"], "deterministic")
            self.assertEqual(report["cycles"][0]["stage_after"], "research")

    def test_deterministic_gate_records_decision_before_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = root / "state.yaml"
            state = new_workflow_state(
                run_id="gate-supervisor",
                strategy_id="fixture-strategy",
                objective="Evaluate exact gate",
                target_gate="research_gate",
                strategy_owner="owner-a",
                run_owner="owner-b",
                ledger_path=root / "ledger.jsonl",
                timestamp="2026-07-11T00:00:00Z",
            )
            state.update(
                {
                    "stage": "research_gate",
                    "reviewer": "independent-reviewer",
                    "package_path": str(root / "package"),
                    "package_id": "pkg_aaaaaaaaaaaaaaaaaaaaaaaa",
                }
            )
            completed = {**state, "stage": "complete", "status": "complete"}
            evaluation = GateEvaluation(
                decision={"gate_result": "pass"},
                exit_code=0,
            )
            with (
                patch("the_pass.workflow_supervisor.evaluate_gate", return_value=evaluation),
                patch("the_pass.workflow_supervisor.write_gate_decision") as write_decision,
                patch("the_pass.workflow_supervisor.append_gate_decision") as append_decision,
                patch("the_pass.workflow_supervisor._decision_is_recorded", return_value=False),
                patch("the_pass.workflow_supervisor.workflow_target_passes", return_value=True),
                patch(
                    "the_pass.workflow_supervisor.advance_workflow_state",
                    return_value=completed,
                ) as advance,
                patch("the_pass.workflow_supervisor.write_workflow_state_atomic") as write_state,
            ):
                _run_deterministic_stage(state_path, state)
            write_decision.assert_called_once()
            append_decision.assert_called_once()
            self.assertEqual(advance.call_args.kwargs["to_stage"], "complete")
            write_state.assert_called_once_with(state_path, completed)

    def test_auto_driver_strips_credentials_from_agent_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = self.make_state(root)

            def blocked_driver(*_args, **kwargs):
                self.assertNotIn("POLYMARKET_PRIVATE_KEY", kwargs["environment"])
                current = read_workflow_state(state_path)
                blocked = advance_workflow_state(
                    current,
                    to_stage=None,
                    status="blocked",
                    next_action="authenticate selected provider",
                    blockers=["fixture provider is unavailable"],
                )
                write_workflow_state_atomic(state_path, blocked)
                return {
                    "exit_code": 2,
                    "duration_ms": 1,
                    "timed_out": False,
                    "output_exceeded": False,
                    "stdout_sha256": "a" * 64,
                    "stderr_sha256": "b" * 64,
                }

            with (
                patch("the_pass.workflow_supervisor.shutil.which", return_value="/fake/cli"),
                patch("the_pass.workflow_supervisor._run_driver", side_effect=blocked_driver),
            ):
                report, exit_code = supervise_workflow(
                    state_path,
                    driver_argv=["auto"],
                    cwd=ROOT,
                    report_path=root / "supervisor.json",
                    max_cycles=2,
                    environment={
                        "PATH": "/usr/bin:/bin",
                        "HOME": str(root),
                        "POLYMARKET_PRIVATE_KEY": "must-not-leak",
                    },
                )
            self.assertEqual((report["status"], exit_code), ("blocked", 2))

    def test_report_cannot_overwrite_workflow_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = self.make_state(root)
            with self.assertRaisesRegex(WorkflowSupervisorError, "distinct file"):
                supervise_workflow(
                    state,
                    driver_argv=["auto"],
                    cwd=ROOT,
                    report_path=state,
                )


if __name__ == "__main__":
    unittest.main()

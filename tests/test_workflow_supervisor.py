from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from the_pass.attestation import ATTESTATION_KEY_ENV, SIGNING_KEY_ENV
from the_pass.gates import GateEvaluation
from the_pass.ledger import append_ledger_entry, build_run_entry
from the_pass.orchestration import new_workflow_state, write_workflow_state_atomic
from the_pass.orchestration import advance_workflow_state, read_workflow_state
from the_pass.workflow_supervisor import (
    WorkflowSupervisorError,
    _exclusive_workflow_lock,
    _run_deterministic_stage,
    inspect_workflow_execution,
    supervise_workflow,
)
from tests.test_validator import EXAMPLE_PACKAGE, prepare_paper_candidate


ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "tests" / "fixtures" / "fake_workflow_driver.py"


class WorkflowSupervisorTests(unittest.TestCase):
    def init_git_root(self, root: Path) -> None:
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(
            ["git", "config", "user.email", "workflow-tests@example.invalid"],
            cwd=root,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Workflow Tests"], cwd=root, check=True
        )
        (root / "README.md").write_text("fixture\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)

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
            state = self.make_state(root)
            before = state.read_bytes()
            with self.assertRaisesRegex(WorkflowSupervisorError, "timed out"):
                supervise_workflow(
                    state,
                    driver_argv=[sys.executable, str(DRIVER), "sleep"],
                    cwd=ROOT,
                    report_path=root / "supervisor.json",
                    timeout_seconds=1,
                )
            self.assertEqual(
                json.loads((root / "supervisor.json").read_text())["status"],
                "failed",
            )
            self.assertEqual(state.read_bytes(), before)

    def test_malformed_proposal_preserves_canonical_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = self.make_state(root)
            before = state.read_bytes()
            with self.assertRaisesRegex(WorkflowSupervisorError, "invalid state"):
                supervise_workflow(
                    state,
                    driver_argv=[sys.executable, str(DRIVER), "malformed"],
                    cwd=ROOT,
                    report_path=root / "supervisor.json",
                    timeout_seconds=5,
                )
            self.assertEqual(state.read_bytes(), before)

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

    def test_rejected_transition_preserves_canonical_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_path = self.make_state(root)
            before = state_path.read_bytes()
            with self.assertRaisesRegex(
                WorkflowSupervisorError, "exactly one transition"
            ):
                supervise_workflow(
                    state_path,
                    driver_argv=[sys.executable, str(DRIVER), "jump"],
                    cwd=ROOT,
                    report_path=root / "supervisor.json",
                    max_cycles=1,
                    timeout_seconds=5,
                )
            self.assertEqual(state_path.read_bytes(), before)
            self.assertFalse(list(root.glob(".*.proposal-*.yaml")))

    def test_same_workflow_state_cannot_be_supervised_concurrently(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = self.make_state(Path(tmp))
            with _exclusive_workflow_lock(state_path):
                with self.assertRaisesRegex(
                    WorkflowSupervisorError, "another supervisor"
                ):
                    with _exclusive_workflow_lock(state_path):
                        pass

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
                proposal_path = Path(kwargs["environment"]["THE_PASS_WORKFLOW_STATE"])
                self.assertNotEqual(proposal_path, state_path)
                current = read_workflow_state(proposal_path)
                blocked = advance_workflow_state(
                    current,
                    to_stage=None,
                    status="blocked",
                    next_action="authenticate selected provider",
                    blockers=["fixture provider is unavailable"],
                )
                write_workflow_state_atomic(proposal_path, blocked)
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

    def test_failed_auto_agent_leaves_caller_workspace_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.init_git_root(root)
            state_path = self.make_state(root)
            state = read_workflow_state(state_path)
            state = advance_workflow_state(
                state,
                to_stage="research",
                status="in_progress",
                next_action="run isolated research",
                timestamp="2026-07-11T00:00:01Z",
            )
            write_workflow_state_atomic(state_path, state)
            before = state_path.read_bytes()

            def malformed_driver(*_args, **kwargs):
                Path(kwargs["cwd"], "uncommitted-side-effect.txt").write_text(
                    "must not escape", encoding="utf-8"
                )
                proposal = Path(kwargs["environment"]["THE_PASS_WORKFLOW_STATE"])
                proposal.write_text("{", encoding="utf-8")
                return {
                    "exit_code": 0,
                    "duration_ms": 1,
                    "timed_out": False,
                    "output_exceeded": False,
                    "stdout_sha256": "a" * 64,
                    "stderr_sha256": "b" * 64,
                }

            with (
                patch("the_pass.workflow_supervisor.shutil.which", return_value="/fake/cli"),
                patch(
                    "the_pass.workflow_supervisor._run_driver",
                    side_effect=malformed_driver,
                ),
                self.assertRaisesRegex(WorkflowSupervisorError, "invalid state"),
            ):
                supervise_workflow(
                    state_path,
                    driver_argv=["auto"],
                    cwd=root,
                    report_path=root / "supervisor.json",
                    max_cycles=1,
                    timeout_seconds=5,
                )
            self.assertEqual(state_path.read_bytes(), before)
            self.assertFalse((root / "uncommitted-side-effect.txt").exists())

    def test_auto_agent_rejects_workspace_symlink_before_driver_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.init_git_root(root)
            state_path = self.make_state(root)
            state = advance_workflow_state(
                read_workflow_state(state_path),
                to_stage="research",
                status="in_progress",
                next_action="run isolated research",
                timestamp="2026-07-11T00:00:01Z",
            )
            write_workflow_state_atomic(state_path, state)
            outside = root.parent / f"{root.name}-outside.txt"
            outside.write_text("outside\n", encoding="utf-8")
            (root / "outside-link").symlink_to(outside)
            try:
                with (
                    patch("the_pass.workflow_supervisor.shutil.which", return_value="/fake/cli"),
                    patch("the_pass.workflow_supervisor._run_driver") as driver,
                    self.assertRaisesRegex(
                        WorkflowSupervisorError, "source cannot contain symlinks"
                    ),
                ):
                    supervise_workflow(
                        state_path,
                        driver_argv=["auto"],
                        cwd=root,
                        report_path=root / "supervisor.json",
                        max_cycles=1,
                        timeout_seconds=5,
                    )
                driver.assert_not_called()
                self.assertEqual(outside.read_text(encoding="utf-8"), "outside\n")
            finally:
                outside.unlink(missing_ok=True)

    def test_valid_auto_agent_commits_declared_evidence_transactionally(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.init_git_root(root)
            state_path = self.make_state(root)
            state = read_workflow_state(state_path)
            state = advance_workflow_state(
                state,
                to_stage="research",
                status="in_progress",
                next_action="run isolated research",
                timestamp="2026-07-11T00:00:01Z",
            )
            write_workflow_state_atomic(state_path, state)

            def valid_driver(*_args, **kwargs):
                worktree = Path(kwargs["cwd"])
                evidence = worktree / "reports" / "isolated-research.txt"
                evidence.parent.mkdir(parents=True, exist_ok=True)
                evidence.write_text("validated evidence\n", encoding="utf-8")
                proposal = Path(kwargs["environment"]["THE_PASS_WORKFLOW_STATE"])
                current = read_workflow_state(proposal)
                blocked = advance_workflow_state(
                    current,
                    to_stage=None,
                    status="blocked",
                    next_action="supply external research input",
                    evidence_paths=[evidence],
                    blockers=["fixture research input is unavailable"],
                    timestamp="2026-07-11T00:00:02Z",
                )
                write_workflow_state_atomic(proposal, blocked)
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
                patch("the_pass.workflow_supervisor._run_driver", side_effect=valid_driver),
            ):
                report, exit_code = supervise_workflow(
                    state_path,
                    driver_argv=["auto"],
                    cwd=root,
                    report_path=root / "supervisor.json",
                    max_cycles=1,
                    timeout_seconds=5,
                )
            transaction = report["cycles"][0]["workspace_transaction"]
            self.assertEqual(exit_code, 2)
            self.assertEqual(transaction["workspace_mode"], "detached_worktree_transaction")
            self.assertEqual(transaction["changed_paths"], ["reports/isolated-research.txt"])
            self.assertEqual(len(transaction["patch_sha256"]), 64)
            self.assertEqual(
                (root / "reports" / "isolated-research.txt").read_text(encoding="utf-8"),
                "validated evidence\n",
            )

    def test_concurrent_caller_change_blocks_auto_agent_patch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.init_git_root(root)
            evidence = root / "reports" / "isolated-research.txt"
            evidence.parent.mkdir(parents=True)
            evidence.write_text("caller baseline\n", encoding="utf-8")
            state_path = self.make_state(root)
            state = advance_workflow_state(
                read_workflow_state(state_path),
                to_stage="research",
                status="in_progress",
                next_action="run isolated research",
                timestamp="2026-07-11T00:00:01Z",
            )
            write_workflow_state_atomic(state_path, state)
            state_before = state_path.read_bytes()

            def racing_driver(*_args, **kwargs):
                isolated_evidence = Path(kwargs["cwd"]) / "reports" / "isolated-research.txt"
                isolated_evidence.write_text("agent proposal\n", encoding="utf-8")
                evidence.write_text("concurrent caller edit\n", encoding="utf-8")
                proposal = Path(kwargs["environment"]["THE_PASS_WORKFLOW_STATE"])
                blocked = advance_workflow_state(
                    read_workflow_state(proposal),
                    to_stage=None,
                    status="blocked",
                    next_action="supply external research input",
                    evidence_paths=[isolated_evidence],
                    blockers=["fixture research input is unavailable"],
                    timestamp="2026-07-11T00:00:02Z",
                )
                write_workflow_state_atomic(proposal, blocked)
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
                patch("the_pass.workflow_supervisor._run_driver", side_effect=racing_driver),
                self.assertRaisesRegex(
                    WorkflowSupervisorError, "caller workspace changed during agent execution"
                ),
            ):
                supervise_workflow(
                    state_path,
                    driver_argv=["auto"],
                    cwd=root,
                    report_path=root / "supervisor.json",
                    max_cycles=1,
                    timeout_seconds=5,
                )
            self.assertEqual(state_path.read_bytes(), state_before)
            self.assertEqual(evidence.read_text(encoding="utf-8"), "concurrent caller edit\n")

    def test_review_transition_waits_for_external_signature_without_leaking_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "package"
            ledger = root / "ledger.jsonl"
            shutil.copytree(EXAMPLE_PACKAGE, package)
            prepare_paper_candidate(package)
            package_id = build_run_entry(package, ledger_path=ledger)["package_id"]
            append_ledger_entry(ledger, package)
            state_path = self.make_state(root)
            state = read_workflow_state(state_path)
            state.update(
                {
                    "stage": "review_research",
                    "reviewer": "independent-auditor",
                    "transitions_used": 5,
                    "package_path": str(package),
                    "package_id": package_id,
                    "evidence_paths": [str(package / "findings.json")],
                    "next_action": "perform independent review",
                }
            )
            write_workflow_state_atomic(state_path, state)

            def review_driver(*_args, **kwargs):
                self.assertNotIn(ATTESTATION_KEY_ENV, kwargs["environment"])
                self.assertNotIn(SIGNING_KEY_ENV, kwargs["environment"])
                proposal = Path(kwargs["environment"]["THE_PASS_WORKFLOW_STATE"])
                current = read_workflow_state(proposal)
                reviewed = advance_workflow_state(
                    current,
                    to_stage="research_gate",
                    status="in_progress",
                    next_action="evaluate research gate",
                    reviewer="independent-auditor",
                    evidence_paths=[package / "findings.json"],
                )
                write_workflow_state_atomic(proposal, reviewed)
                return {
                    "exit_code": 0,
                    "duration_ms": 1,
                    "timed_out": False,
                    "output_exceeded": False,
                    "stdout_sha256": "a" * 64,
                    "stderr_sha256": "b" * 64,
                }

            with patch(
                "the_pass.workflow_supervisor._run_driver", side_effect=review_driver
            ):
                report, exit_code = supervise_workflow(
                    state_path,
                    driver_argv=["trusted-review-driver"],
                    cwd=ROOT,
                    report_path=root / "supervisor.json",
                    author_provider="codex",
                    available_providers=("claude",),
                    max_cycles=1,
                    environment={
                        ATTESTATION_KEY_ENV: "legacy-key-must-not-leak-32-bytes",
                        SIGNING_KEY_ENV: "private-key-must-not-leak",
                    },
                )

            attestation_path = (
                package / "reviewer_attestation.research_gate.json"
            )
            final_state = read_workflow_state(state_path)
            self.assertEqual(exit_code, 2)
            self.assertEqual(report["cycles"][0]["stage_after"], "review_research")
            self.assertEqual(final_state["status"], "waiting")
            self.assertIn("Ed25519", final_state["blockers"][0])
            self.assertFalse(attestation_path.exists())
            report_text = (root / "supervisor.json").read_text()
            self.assertNotIn("legacy-key-must-not-leak", report_text)
            self.assertNotIn("private-key-must-not-leak", report_text)

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

from __future__ import annotations

import hashlib
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from the_pass.cli import build_parser, main as cli_main
from the_pass.ledger import build_run_entry
from the_pass.orchestration import (
    PUBLIC_SKILLS,
    ForbiddenWorkflowError,
    WorkflowError,
    advance_workflow_state,
    create_superseding_package,
    load_pipeline_policy,
    new_workflow_state,
    read_workflow_state,
    validate_workflow_state,
    verify_workflow_evidence,
    write_workflow_state_atomic,
)
from the_pass.validator import validate_package


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PACKAGE = ROOT / "examples" / "synthetic-breakout" / "package"


def tree_fingerprint(path: Path) -> str:
    digest = hashlib.sha256()
    for item in sorted(
        candidate for candidate in path.rglob("*") if candidate.is_file()
    ):
        digest.update(item.relative_to(path).as_posix().encode("utf-8"))
        digest.update(item.read_bytes())
    return digest.hexdigest()


class OrchestrationTests(unittest.TestCase):
    def make_state(self, target_gate: str = "research_gate") -> dict:
        return new_workflow_state(
            run_id="run-1",
            objective="evaluate a preregistered strategy",
            target_gate=target_gate,
            strategy_owner="strategy-owner",
            run_owner="run-owner",
            ledger_path=Path("receipts/ledger.jsonl"),
            timestamp="2026-07-10T00:00:00Z",
        )

    def test_policy_defines_exactly_seven_public_skills_and_parseable_cli_contracts(
        self,
    ) -> None:
        policy = load_pipeline_policy(ROOT / "config" / "skill-pipeline.v1.yaml")
        parser = build_parser()

        self.assertEqual(tuple(policy["public_skills"]), PUBLIC_SKILLS)
        self.assertEqual(len(list((ROOT / "skills").glob("*/SKILL.md"))), 7)
        for contract in policy["cli_contracts"].values():
            parser.parse_args([str(value) for value in contract["argv"]])

    def test_state_round_trip_is_atomic_and_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state_path = Path(tmp) / ".the-pass" / "runs" / "run-1" / "state.yaml"
            expected = self.make_state()
            write_workflow_state_atomic(state_path, expected)
            actual = read_workflow_state(state_path)

        self.assertEqual(actual, expected)

    def test_forged_terminal_reviewer_and_timestamp_state_is_rejected(self) -> None:
        terminal = self.make_state()
        terminal["status"] = "complete"
        with self.assertRaisesRegex(WorkflowError, "complete stage"):
            validate_workflow_state(terminal)

        waiting = self.make_state()
        waiting["status"] = "waiting"
        with self.assertRaisesRegex(WorkflowError, "requires at least one reason"):
            validate_workflow_state(waiting)

        reviewer = self.make_state()
        reviewer["stage"] = "review_research"
        with self.assertRaisesRegex(WorkflowError, "independent review stage"):
            validate_workflow_state(reviewer)

        timestamp = self.make_state()
        timestamp["updated_at"] = "2026-07-09T23:59:59Z"
        with self.assertRaisesRegex(WorkflowError, "ordered RFC3339"):
            validate_workflow_state(timestamp)

        forged_stage = self.make_state("risk_review")
        forged_stage["stage"] = "risk_prepare"
        with self.assertRaisesRegex(WorkflowError, "requires a verified ledger"):
            verify_workflow_evidence(forged_stage)

        missing_evidence = self.make_state()
        missing_evidence["evidence_paths"] = ["/definitely/missing/evidence.json"]
        with self.assertRaisesRegex(WorkflowError, "evidence path is missing"):
            verify_workflow_evidence(missing_evidence)

    def test_live_gate_target_is_forbidden(self) -> None:
        with self.assertRaises(ForbiddenWorkflowError):
            self.make_state("live_gate")

    def test_illegal_transition_is_rejected(self) -> None:
        with self.assertRaises(WorkflowError):
            advance_workflow_state(
                self.make_state(),
                to_stage="complete",
                status="complete",
                next_action="done",
            )

    @patch("the_pass.orchestration.verify_workflow_evidence")
    def test_workflow_can_only_complete_at_its_target_gate(
        self, _verify_evidence
    ) -> None:
        research_state = advance_workflow_state(
            self.make_state("research_gate"),
            to_stage="research_gate",
            status="in_progress",
            next_action="evaluate research gate",
            reviewer="independent-reviewer",
        )
        with self.assertRaises(WorkflowError):
            advance_workflow_state(
                research_state,
                to_stage="paper_prepare",
                status="in_progress",
                next_action="continue to paper",
            )
        with self.assertRaisesRegex(WorkflowError, "verified exact-package"):
            advance_workflow_state(
                research_state,
                to_stage="complete",
                status="complete",
                next_action="unverified target gate",
            )
        with patch("the_pass.orchestration.workflow_target_passes", return_value=True):
            completed = advance_workflow_state(
                research_state,
                to_stage="complete",
                status="complete",
                next_action="target gate passed",
            )

        paper_state = advance_workflow_state(
            self.make_state("paper_gate"),
            to_stage="research_gate",
            status="in_progress",
            next_action="evaluate prerequisite gate",
            reviewer="independent-reviewer",
        )
        with self.assertRaises(WorkflowError):
            advance_workflow_state(
                paper_state,
                to_stage="complete",
                status="complete",
                next_action="incorrect early completion",
            )

        self.assertEqual(completed["status"], "complete")

    def test_blocked_state_requires_explicit_resume(self) -> None:
        blocked = advance_workflow_state(
            self.make_state(),
            to_stage="research",
            status="blocked",
            next_action="provide data",
            blockers=["required dataset is unavailable"],
        )
        with self.assertRaisesRegex(WorkflowError, "explicit resume"):
            advance_workflow_state(
                blocked,
                to_stage="screen",
                status="in_progress",
                next_action="continue",
            )

        resumed = advance_workflow_state(
            blocked,
            to_stage="screen",
            status="in_progress",
            next_action="continue with verified data",
            resume=True,
        )
        self.assertEqual(
            (resumed["stage"], resumed["status"]), ("screen", "in_progress")
        )

    @patch("the_pass.orchestration.verify_workflow_evidence")
    def test_independent_review_requires_a_distinct_reviewer(
        self, _verify_evidence
    ) -> None:
        for reviewer in (None, "strategy-owner", "run-owner"):
            with self.subTest(reviewer=reviewer):
                blocked = advance_workflow_state(
                    self.make_state(),
                    to_stage="review_research",
                    status="in_progress",
                    next_action="review",
                    reviewer=reviewer,
                )
                validate_workflow_state(blocked)
                self.assertEqual(blocked["status"], "blocked")

        reviewed = advance_workflow_state(
            self.make_state(),
            to_stage="review_research",
            status="in_progress",
            next_action="review package",
            reviewer="independent-reviewer",
        )
        self.assertEqual(reviewed["stage"], "review_research")
        self.assertEqual(reviewed["reviewer"], "independent-reviewer")

    def test_two_no_progress_remediation_laps_block_the_run(self) -> None:
        state = advance_workflow_state(
            self.make_state(),
            to_stage="research",
            status="in_progress",
            next_action="formalize hypothesis",
        )
        state = advance_workflow_state(
            state,
            to_stage="remediation",
            status="in_progress",
            next_action="repair first finding",
        )
        state = advance_workflow_state(
            state,
            to_stage=None,
            status="in_progress",
            next_action="retry first repair",
            remediation=True,
            moved_gate=False,
        )
        state = advance_workflow_state(
            state,
            to_stage=None,
            status="in_progress",
            next_action="retry second repair",
            remediation=True,
            moved_gate=False,
        )

        validate_workflow_state(state)
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["no_progress_laps"], 2)

    def test_exhausted_transition_budget_returns_a_valid_blocked_state(self) -> None:
        policy = load_pipeline_policy()
        state = self.make_state()
        state["transitions_used"] = policy["runtime"]["max_transitions"]

        blocked = advance_workflow_state(
            state,
            to_stage="research",
            status="in_progress",
            next_action="continue",
        )

        validate_workflow_state(blocked)
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(
            blocked["transitions_used"], policy["runtime"]["max_transitions"]
        )

    def test_superseding_package_preserves_source_and_gets_new_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            target = root / "target"
            shutil.copytree(EXAMPLE_PACKAGE, source)
            (source / "ledger.jsonl").write_text(
                "historical local ledger\n", encoding="utf-8"
            )
            before = tree_fingerprint(source)
            source_id = build_run_entry(source)["package_id"]

            created, target_id = create_superseding_package(
                source,
                target,
                run_id="superseding-run-2",
                created_at="2026-07-10T01:00:00Z",
            )

            receipt = json.loads(
                (target / "run_receipt.json").read_text(encoding="utf-8")
            )
            self.assertEqual(tree_fingerprint(source), before)
            self.assertEqual(created, target.resolve())
            self.assertNotEqual(target_id, source_id)
            self.assertEqual(receipt["supersedes_package_id"], source_id)
            self.assertFalse((target / "ledger.jsonl").exists())
            self.assertTrue(validate_package(target).ok)

    def test_state_resume_recomputes_package_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "package"
            state_path = root / "state.yaml"
            shutil.copytree(EXAMPLE_PACKAGE, package)
            package_id = build_run_entry(package)["package_id"]
            state = advance_workflow_state(
                self.make_state(),
                to_stage="research",
                status="in_progress",
                next_action="continue",
                package_path=str(package),
                package_id=package_id,
            )
            write_workflow_state_atomic(state_path, state)
            self.assertEqual(read_workflow_state(state_path), state)

            metrics_path = package / "metrics_report.json"
            metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
            metrics["limitations"].append("tampered after state checkpoint")
            metrics_path.write_text(json.dumps(metrics), encoding="utf-8")
            with self.assertRaisesRegex(WorkflowError, "package_id does not match"):
                read_workflow_state(state_path)

    def test_high_stage_resume_requires_declared_stage_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "package"
            ledger = root / "ledger.jsonl"
            shutil.copytree(EXAMPLE_PACKAGE, package)
            ledger.touch()
            for name in (
                "risk_policy.json",
                "risk_report.json",
                "approval_pack.json",
                "config_diff.json",
            ):
                (package / name).write_text("{}", encoding="utf-8")
            package_id = "pkg_" + "a" * 24
            artifacts = [
                {"type": "risk_report", "path": "risk_report.json", "sha256": "a" * 64}
            ]
            entries = [
                {"entry_kind": "run", "package_id": package_id, "artifacts": artifacts},
                {
                    "schema": "the-pass/receipt-ledger-entry/v2",
                    "entry_kind": "gate_decision",
                    "package_id": package_id,
                    "gate": "research_gate",
                    "gate_result": "pass",
                },
                {
                    "schema": "the-pass/receipt-ledger-entry/v2",
                    "entry_kind": "gate_decision",
                    "package_id": package_id,
                    "gate": "paper_gate",
                    "gate_result": "pass",
                },
            ]
            state = self.make_state("risk_review")
            state.update(
                {
                    "stage": "review_risk",
                    "reviewer": "independent-reviewer",
                    "package_path": str(package),
                    "package_id": package_id,
                    "ledger_path": str(ledger),
                    "evidence_paths": [],
                }
            )

            with (
                patch("the_pass.orchestration.verify_ledger_file", return_value=[]),
                patch(
                    "the_pass.orchestration.read_ledger_entries", return_value=entries
                ),
                patch("the_pass.orchestration.validate_package") as package_validation,
                patch(
                    "the_pass.orchestration.build_run_entry",
                    return_value={"package_id": package_id, "artifacts": artifacts},
                ),
            ):
                package_validation.return_value.ok = True
                package_validation.return_value.issues = []
                with self.assertRaisesRegex(
                    WorkflowError, "must list risk_policy.json"
                ):
                    verify_workflow_evidence(state)

    def test_superseding_package_rejects_same_run_id_nested_target_and_symlink(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            shutil.copytree(EXAMPLE_PACKAGE, source)
            source_run_id = json.loads(
                (source / "run_receipt.json").read_text(encoding="utf-8")
            )["id"]

            with self.assertRaisesRegex(WorkflowError, "different from the source"):
                create_superseding_package(
                    source,
                    Path(tmp) / "same-run",
                    run_id=source_run_id,
                    created_at="2026-07-10T01:00:00Z",
                )
            with self.assertRaisesRegex(WorkflowError, "outside the source"):
                create_superseding_package(
                    source,
                    source / "nested",
                    run_id="new-run",
                    created_at="2026-07-10T01:00:00Z",
                )

            (source / "external-link").symlink_to(Path(tmp) / "outside")
            with self.assertRaisesRegex(WorkflowError, "symbolic links"):
                create_superseding_package(
                    source,
                    Path(tmp) / "symlink-target",
                    run_id="new-run",
                    created_at="2026-07-10T01:00:00Z",
                )

    def test_workflow_cli_has_stable_json_envelope_and_forbidden_exit(self) -> None:
        required = {"ok", "status", "artifact_paths", "issues", "receipt_id"}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state = root / "state.yaml"
            ledger = root / "ledger.jsonl"
            start_output = io.StringIO()
            with redirect_stdout(start_output):
                start_exit = cli_main(
                    [
                        "workflow",
                        "start",
                        "--state",
                        str(state),
                        "--run-id",
                        "run-1",
                        "--objective",
                        "evaluate strategy",
                        "--target-gate",
                        "research_gate",
                        "--strategy-owner",
                        "strategy-owner",
                        "--run-owner",
                        "run-owner",
                        "--ledger",
                        str(ledger),
                        "--format",
                        "json",
                    ]
                )
            status_output = io.StringIO()
            with redirect_stdout(status_output):
                status_exit = cli_main(
                    ["workflow", "status", "--state", str(state), "--format", "json"]
                )
            forbidden_output = io.StringIO()
            with redirect_stdout(forbidden_output):
                forbidden_exit = cli_main(
                    [
                        "workflow",
                        "start",
                        "--state",
                        str(root / "live.yaml"),
                        "--run-id",
                        "run-live",
                        "--objective",
                        "live",
                        "--target-gate",
                        "live_gate",
                        "--strategy-owner",
                        "strategy-owner",
                        "--run-owner",
                        "run-owner",
                        "--ledger",
                        str(ledger),
                        "--format",
                        "json",
                    ]
                )
            fingerprint_output = io.StringIO()
            with redirect_stdout(fingerprint_output):
                fingerprint_exit = cli_main(
                    [
                        "workflow",
                        "fingerprint",
                        str(EXAMPLE_PACKAGE),
                        "--format",
                        "json",
                    ]
                )

        documents = [
            json.loads(stream.getvalue())
            for stream in (
                start_output,
                status_output,
                forbidden_output,
                fingerprint_output,
            )
        ]
        self.assertEqual(
            (start_exit, status_exit, forbidden_exit, fingerprint_exit), (0, 0, 3, 0)
        )
        self.assertTrue(all(required.issubset(document) for document in documents))
        self.assertEqual(documents[2]["status"], "forbidden")
        self.assertTrue(documents[3]["receipt_id"].startswith("pkg_"))


if __name__ == "__main__":
    unittest.main()

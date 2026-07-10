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
from the_pass.ledger import (
    LedgerError,
    append_ledger_entry,
    build_run_entry,
    hash_entry,
    verify_ledger_file,
)
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
    verify_remediation_progress,
    verify_target_remediation_entry,
    verify_workflow_evidence,
    write_workflow_state_atomic,
)
from the_pass.validator import validate_artifact, validate_package


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_PACKAGE = ROOT / "examples" / "synthetic-breakout" / "package"


def write_confirmed_findings(
    path: Path, *, target_gate: str = "research_gate", package: str = "."
) -> dict:
    document = {
        "schema_version": 2,
        "id": "confirmed-remediation-finding",
        "created_at": "2026-07-10T00:00:00Z",
        "package": package,
        "reviewer": "independent-reviewer",
        "target_gate": target_gate,
        "findings": [
            {
                "id": "finding-1",
                "severity": "P1",
                "status": "confirmed",
                "title": "Confirmed gate blocker",
                "evidence": {
                    "artifact": "metrics_report",
                    "path": "metrics_report.json",
                    "note": "reproduced mismatch",
                },
                "blocks_promotion": True,
                "recommendation": "create a scoped successor",
            }
        ],
        "summary": {
            "gate_result": "revise",
            "unresolved_blockers": ["confirmed gate blocker"],
            "next_action": "remediate the confirmed finding",
        },
    }
    path.write_text(json.dumps(document), encoding="utf-8")
    return document


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

    @patch("the_pass.orchestration.verify_target_remediation_entry")
    @patch("the_pass.orchestration.verify_workflow_evidence")
    @patch("the_pass.orchestration.workflow_target_passes", return_value=False)
    def test_failed_target_gate_can_block_kill_resume_or_enter_remediation(
        self, _target_passes, _verify_evidence, _verify_remediation
    ) -> None:
        target = advance_workflow_state(
            self.make_state("research_gate"),
            to_stage="research_gate",
            status="in_progress",
            next_action="evaluate target gate",
            reviewer="independent-reviewer",
        )
        blocked = advance_workflow_state(
            target,
            to_stage=None,
            status="blocked",
            next_action="resolve missing evidence",
            blockers=["research gate blocked"],
        )
        resumed = advance_workflow_state(
            blocked,
            to_stage=None,
            status="in_progress",
            next_action="reevaluate target gate",
            reviewer="independent-reviewer",
            resume=True,
        )
        remediation = advance_workflow_state(
            resumed,
            to_stage="remediation",
            status="in_progress",
            next_action="repair confirmed finding",
            evidence_paths=[str(EXAMPLE_PACKAGE / "verdict_report.json")],
            blockers=[],
        )
        killed = advance_workflow_state(
            target,
            to_stage=None,
            status="killed",
            next_action="archive killed hypothesis",
            blockers=["declared kill condition reached"],
        )

        self.assertEqual(
            (blocked["stage"], blocked["status"]), ("research_gate", "blocked")
        )
        self.assertEqual(
            (resumed["stage"], resumed["status"]), ("research_gate", "in_progress")
        )
        self.assertEqual(remediation["stage"], "remediation")
        self.assertEqual(remediation["remediation_laps"], 1)
        self.assertEqual(remediation["no_progress_laps"], 1)
        self.assertEqual(
            remediation["transitions_used"], resumed["transitions_used"] + 1
        )
        self.assertEqual(killed["status"], "killed")

    @patch("the_pass.orchestration.verify_workflow_evidence")
    @patch("the_pass.orchestration.workflow_target_passes", return_value=False)
    def test_target_remediation_requires_confirmed_finding_evidence(
        self, _target_passes, _verify_evidence
    ) -> None:
        target = advance_workflow_state(
            self.make_state("research_gate"),
            to_stage="research_gate",
            status="in_progress",
            next_action="evaluate target gate",
            reviewer="independent-reviewer",
        )

        with self.assertRaisesRegex(WorkflowError, "requires evidence paths"):
            advance_workflow_state(
                target,
                to_stage="remediation",
                status="in_progress",
                next_action="repair an unproven finding",
            )

    @patch("the_pass.orchestration._confirmed_finding_artifact")
    def test_remediation_rejects_waiting_or_blocked_entry(self, _confirmed) -> None:
        state = advance_workflow_state(
            self.make_state(),
            to_stage="research",
            status="in_progress",
            next_action="formalize hypothesis",
        )
        evidence = [str(EXAMPLE_PACKAGE / "verdict_report.json")]

        for status in ("waiting", "blocked"):
            with self.subTest(status=status), self.assertRaisesRegex(
                WorkflowError, "only in_progress"
            ):
                advance_workflow_state(
                    state,
                    to_stage="remediation",
                    status=status,
                    next_action="invalid remediation entry",
                    blockers=["not an active remediation attempt"],
                    evidence_paths=evidence,
                )

    def test_target_remediation_requires_recorded_nonpass_package_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "package"
            package.mkdir()
            findings_path = package / "findings.json"
            findings = write_confirmed_findings(findings_path)
            package_id = "pkg_" + "a" * 24
            ledger = root / "ledger.jsonl"
            ledger.touch()
            state = self.make_state("research_gate")
            state.update(
                {
                    "stage": "research_gate",
                    "reviewer": findings["reviewer"],
                    "package_path": str(package),
                    "package_id": package_id,
                    "ledger_path": str(ledger),
                }
            )
            run_entry = {
                "schema": "the-pass/receipt-ledger-entry/v2",
                "entry_kind": "run",
                "package_id": package_id,
                "package_path": "package",
            }
            gate_entry = {
                "schema": "the-pass/receipt-ledger-entry/v2",
                "entry_kind": "gate_decision",
                "package_id": package_id,
                "package_path": "package",
                "gate": "research_gate",
                "gate_result": "revise",
                "reviewer": findings["reviewer"],
                "artifacts": [
                    {
                        "type": "findings",
                        "path": "findings.json",
                        "sha256": hashlib.sha256(
                            findings_path.read_bytes()
                        ).hexdigest(),
                    }
                ],
            }

            with (
                patch("the_pass.orchestration.verify_ledger_file", return_value=[]),
                patch(
                    "the_pass.orchestration.read_ledger_entries",
                    return_value=[run_entry, gate_entry],
                ),
            ):
                verify_target_remediation_entry(state, [str(findings_path)])

            legacy_entries = [
                {**run_entry, "schema": "the-pass/receipt-ledger-entry/v1"},
                {**gate_entry, "schema": "the-pass/receipt-ledger-entry/v1"},
            ]
            with (
                patch("the_pass.orchestration.verify_ledger_file", return_value=[]),
                patch(
                    "the_pass.orchestration.read_ledger_entries",
                    return_value=legacy_entries,
                ),
                self.assertRaisesRegex(WorkflowError, "exact recorded run"),
            ):
                verify_target_remediation_entry(state, [str(findings_path)])

            with (
                patch("the_pass.orchestration.verify_ledger_file", return_value=[]),
                patch(
                    "the_pass.orchestration.read_ledger_entries",
                    return_value=[run_entry],
                ),
                self.assertRaisesRegex(WorkflowError, "recorded blocked or revise"),
            ):
                verify_target_remediation_entry(state, [str(findings_path)])

            external_findings = root / "findings.json"
            external_findings.write_bytes(findings_path.read_bytes())
            with self.assertRaisesRegex(WorkflowError, "inside the exact package"):
                verify_target_remediation_entry(state, [str(external_findings)])

    @patch("the_pass.orchestration.verify_workflow_evidence")
    def test_healthy_incomplete_paper_window_waits_and_resumes(
        self, _verify_evidence
    ) -> None:
        waiting = advance_workflow_state(
            self.make_state("paper_gate"),
            to_stage="paper_observe",
            status="waiting",
            next_action="continue observation after more elapsed market time",
            blockers=["minimum paper observation window is incomplete"],
        )
        resumed = advance_workflow_state(
            waiting,
            to_stage=None,
            status="in_progress",
            next_action="resume healthy paper observation",
        )

        self.assertEqual(
            (waiting["stage"], waiting["status"]), ("paper_observe", "waiting")
        )
        self.assertEqual(
            (resumed["stage"], resumed["status"]), ("paper_observe", "in_progress")
        )

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

    @patch("the_pass.orchestration._confirmed_finding_artifact")
    def test_two_no_progress_remediation_laps_block_the_run(self, _confirmed) -> None:
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
            evidence_paths=[str(EXAMPLE_PACKAGE / "verdict_report.json")],
        )
        state = advance_workflow_state(
            state,
            to_stage=None,
            status="in_progress",
            next_action="retry first repair",
        )

        validate_workflow_state(state)
        self.assertEqual(state["status"], "blocked")
        self.assertEqual(state["remediation_laps"], 2)
        self.assertEqual(state["no_progress_laps"], 2)

        with self.assertRaisesRegex(WorkflowError, "non-resumable"):
            advance_workflow_state(
                state,
                to_stage="screen",
                status="in_progress",
                next_action="escape exhausted remediation",
                resume=True,
            )

    @patch("the_pass.orchestration._confirmed_finding_artifact")
    def test_moved_gate_requires_a_recorded_successor(self, _confirmed) -> None:
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
            next_action="repair confirmed finding",
            evidence_paths=[str(EXAMPLE_PACKAGE / "verdict_report.json")],
        )

        with self.assertRaisesRegex(WorkflowError, "recorded successor"):
            advance_workflow_state(
                state,
                to_stage=None,
                status="in_progress",
                next_action="claim unsupported gate progress",
                moved_gate=True,
            )

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

    @patch("the_pass.orchestration.verify_workflow_evidence")
    @patch("the_pass.orchestration.workflow_target_passes", return_value=True)
    def test_passed_target_completes_at_transition_budget_boundary(
        self, _target_passes, _verify_evidence
    ) -> None:
        policy = load_pipeline_policy()
        state = self.make_state("research_gate")
        state["stage"] = "research_gate"
        state["status"] = "in_progress"
        state["reviewer"] = "independent-reviewer"
        state["transitions_used"] = policy["runtime"]["max_transitions"]

        completed = advance_workflow_state(
            state,
            to_stage="complete",
            status="complete",
            next_action="target gate passed",
        )

        validate_workflow_state(completed)
        self.assertEqual(completed["stage"], "complete")
        self.assertEqual(completed["status"], "complete")
        self.assertEqual(
            completed["transitions_used"], policy["runtime"]["max_transitions"]
        )

    def test_superseding_package_preserves_source_and_gets_new_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source"
            target = root / "target"
            ledger = root / "ledger.jsonl"
            shutil.copytree(EXAMPLE_PACKAGE, source)
            append_ledger_entry(ledger, source)
            before = tree_fingerprint(source)
            source_id = build_run_entry(source, ledger_path=ledger)["package_id"]

            created, target_id = create_superseding_package(
                source,
                target,
                ledger_path=ledger,
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
            self.assertTrue(validate_package(target).ok)
            append_ledger_entry(ledger, target)
            self.assertFalse(verify_ledger_file(ledger))

            state = self.make_state()
            state.update(
                {
                    "package_path": str(source),
                    "package_id": source_id,
                    "ledger_path": str(ledger),
                }
            )
            verify_remediation_progress(state, str(target), target_id)

    def test_ledger_append_rejects_forged_successor_lineage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "package"
            ledger = root / "ledger.jsonl"
            shutil.copytree(EXAMPLE_PACKAGE, package)
            receipt_path = package / "run_receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt.update(
                {
                    "supersedes_package_id": "pkg_" + "f" * 24,
                    "supersedes_artifacts_hash": "f" * 64,
                }
            )
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

            with self.assertRaisesRegex(LedgerError, "unknown prior v2 package"):
                append_ledger_entry(ledger, package)

            forged_entry = build_run_entry(package, ledger_path=ledger)
            forged_entry["entry_hash"] = hash_entry(forged_entry)
            ledger.write_text(json.dumps(forged_entry) + "\n", encoding="utf-8")
            issues = verify_ledger_file(ledger)
            self.assertTrue(
                any("unknown prior v2 package" in issue.message for issue in issues),
                [issue.as_dict() for issue in issues],
            )

    def test_partial_successor_lineage_fails_public_artifact_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            receipt_path = Path(tmp) / "run_receipt.json"
            receipt = json.loads(
                (EXAMPLE_PACKAGE / "run_receipt.json").read_text(encoding="utf-8")
            )
            receipt["supersedes_package_id"] = "pkg_" + "a" * 24
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

            result = validate_artifact(receipt_path, artifact_type="run_receipt")

        self.assertFalse(result.ok)
        self.assertTrue(
            any("requires both" in issue.message for issue in result.issues),
            [issue.as_dict() for issue in result.issues],
        )

    def test_workflow_rejects_unrecorded_copy_of_recorded_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recorded = root / "recorded"
            copied = root / "copied"
            ledger = root / "ledger.jsonl"
            shutil.copytree(EXAMPLE_PACKAGE, recorded)
            append_ledger_entry(ledger, recorded)
            shutil.copytree(recorded, copied)
            package_id = build_run_entry(recorded, ledger_path=ledger)["package_id"]
            state = self.make_state()
            state.update(
                {
                    "stage": "robustness",
                    "package_path": str(copied),
                    "package_id": package_id,
                    "ledger_path": str(ledger),
                }
            )

            with self.assertRaisesRegex(WorkflowError, "exact package run"):
                verify_workflow_evidence(state)

    def test_superseding_package_rejects_unrecorded_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source"
            target = Path(tmp) / "target"
            ledger = Path(tmp) / "ledger.jsonl"
            shutil.copytree(EXAMPLE_PACKAGE, source)
            ledger.touch()

            with self.assertRaisesRegex(WorkflowError, "not recorded"):
                create_superseding_package(
                    source,
                    target,
                    ledger_path=ledger,
                    run_id="new-run",
                    created_at="2026-07-10T01:00:00Z",
                )

    def test_superseding_package_rejects_an_unrecorded_copy_of_a_recorded_package(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recorded = root / "recorded"
            copied = root / "copied"
            ledger = root / "ledger.jsonl"
            shutil.copytree(EXAMPLE_PACKAGE, recorded)
            append_ledger_entry(ledger, recorded)
            shutil.copytree(recorded, copied)

            with self.assertRaisesRegex(WorkflowError, "source path does not match"):
                create_superseding_package(
                    copied,
                    root / "target",
                    ledger_path=ledger,
                    run_id="new-run",
                    created_at="2026-07-10T01:00:00Z",
                )

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
                {
                    "schema": "the-pass/receipt-ledger-entry/v2",
                    "entry_kind": "run",
                    "package_id": package_id,
                    "package_path": "package",
                    "artifacts": artifacts,
                },
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
            ledger = Path(tmp) / "ledger.jsonl"
            shutil.copytree(EXAMPLE_PACKAGE, source)
            append_ledger_entry(ledger, source)
            source_run_id = json.loads(
                (source / "run_receipt.json").read_text(encoding="utf-8")
            )["id"]

            with self.assertRaisesRegex(WorkflowError, "different from the source"):
                create_superseding_package(
                    source,
                    Path(tmp) / "same-run",
                    ledger_path=ledger,
                    run_id=source_run_id,
                    created_at="2026-07-10T01:00:00Z",
                )
            with self.assertRaisesRegex(WorkflowError, "outside the source"):
                create_superseding_package(
                    source,
                    source / "nested",
                    ledger_path=ledger,
                    run_id="new-run",
                    created_at="2026-07-10T01:00:00Z",
                )

            (source / "external-link").symlink_to(Path(tmp) / "outside")
            with self.assertRaisesRegex(WorkflowError, "symbolic links"):
                create_superseding_package(
                    source,
                    Path(tmp) / "symlink-target",
                    ledger_path=ledger,
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

from __future__ import annotations

import hashlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout
from unittest.mock import patch

from the_pass.attestation import (
    ATTESTATION_KEY_ENV,
    AttestationError,
    create_reviewer_attestation,
    verify_reviewer_attestation,
    write_reviewer_attestation,
)
from the_pass.gates import evaluate_gate
from the_pass.cli import main as cli_main
from the_pass.ledger import build_run_entry
from tests.test_validator import EXAMPLE_PACKAGE, prepare_paper_candidate


KEY = "review-attestation-test-key-32-bytes-minimum"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def evidence() -> dict[str, str]:
    return {
        "state_before_sha256": hashlib.sha256(b"before").hexdigest(),
        "state_after_sha256": hashlib.sha256(b"after").hexdigest(),
        "stdout_sha256": EMPTY_SHA256,
        "stderr_sha256": EMPTY_SHA256,
        "task_sha256": hashlib.sha256(b"review task").hexdigest(),
    }


class ReviewerAttestationTests(unittest.TestCase):
    def test_valid_attestation_verifies_and_tampering_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "reviewer_attestation.research_gate.json"
            document = create_reviewer_attestation(
                gate="research_gate",
                package_id="pkg_" + "a" * 24,
                reviewer="reviewer",
                principal_type="provider",
                provider="claude",
                model="claude-current",
                run_id="run-1",
                author_provider="codex",
                reviewer_provider="claude",
                evidence=evidence(),
                key=KEY,
                created_at="2026-07-15T00:00:00Z",
            )
            write_reviewer_attestation(path, document)
            _, blockers = verify_reviewer_attestation(
                path,
                gate="research_gate",
                package_id="pkg_" + "a" * 24,
                reviewer="reviewer",
                key=KEY,
            )
            self.assertEqual(blockers, [])
            _, wrong_package = verify_reviewer_attestation(
                path,
                gate="research_gate",
                package_id="pkg_" + "b" * 24,
                reviewer="reviewer",
                key=KEY,
            )
            self.assertIn("reviewer attestation package_id does not match", wrong_package)
            _, wrong_reviewer = verify_reviewer_attestation(
                path,
                gate="research_gate",
                package_id="pkg_" + "a" * 24,
                reviewer="other-reviewer",
                key=KEY,
            )
            self.assertIn("reviewer attestation reviewer does not match", wrong_reviewer)
            _, wrong_key = verify_reviewer_attestation(
                path,
                gate="research_gate",
                package_id="pkg_" + "a" * 24,
                reviewer="reviewer",
                key="different-review-attestation-key-32-bytes",
            )
            self.assertIn("reviewer attestation key_id does not match", wrong_key)

            tampered = json.loads(path.read_text(encoding="utf-8"))
            tampered["principal"]["model"] = "changed"
            path.write_text(json.dumps(tampered), encoding="utf-8")
            _, blockers = verify_reviewer_attestation(
                path,
                gate="research_gate",
                package_id="pkg_" + "a" * 24,
                reviewer="reviewer",
                key=KEY,
            )
            self.assertIn("reviewer attestation signature does not verify", blockers)

    def test_automated_same_provider_is_rejected(self) -> None:
        with self.assertRaisesRegex(AttestationError, "differ"):
            create_reviewer_attestation(
                gate="research_gate",
                package_id="pkg_" + "a" * 24,
                reviewer="reviewer",
                principal_type="provider",
                provider="codex",
                model="gpt-current",
                run_id="run-1",
                author_provider="codex",
                reviewer_provider="codex",
                evidence=evidence(),
                key=KEY,
            )

    def test_gate_pass_requires_matching_signed_attestation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "package"
            shutil.copytree(EXAMPLE_PACKAGE, package)
            prepare_paper_candidate(package)
            with patch.dict("os.environ", {ATTESTATION_KEY_ENV: KEY}):
                missing = evaluate_gate(
                    package,
                    gate="research_gate",
                    reviewer="independent-auditor",
                )
                self.assertEqual(missing.exit_code, 2)
                self.assertTrue(
                    any("missing reviewer_attestation" in value for value in missing.decision["blockers"])
                )

                package_id = build_run_entry(package)["package_id"]
                wrong_evidence = create_reviewer_attestation(
                    gate="research_gate",
                    package_id=package_id,
                    reviewer="independent-auditor",
                    principal_type="provider",
                    provider="claude",
                    model="claude-current",
                    run_id="run-1",
                    author_provider="codex",
                    reviewer_provider="claude",
                    evidence=evidence(),
                    key=KEY,
                )
                path = package / "reviewer_attestation.research_gate.json"
                write_reviewer_attestation(path, wrong_evidence)
                wrong = evaluate_gate(
                    package,
                    gate="research_gate",
                    reviewer="independent-auditor",
                )
                self.assertIn(
                    "reviewer attestation task evidence fingerprint does not match",
                    wrong.decision["blockers"],
                )
                path.unlink()
                document = create_reviewer_attestation(
                    gate="research_gate",
                    package_id=package_id,
                    reviewer="independent-auditor",
                    principal_type="provider",
                    provider="claude",
                    model="claude-current",
                    run_id="run-1",
                    author_provider="codex",
                    reviewer_provider="claude",
                    evidence={
                        **evidence(),
                        "task_sha256": hashlib.sha256(
                            (package / "findings.json").read_bytes()
                        ).hexdigest(),
                    },
                    key=KEY,
                )
                write_reviewer_attestation(path, document)
                passed = evaluate_gate(
                    package,
                    gate="research_gate",
                    reviewer="independent-auditor",
                )

            self.assertEqual(passed.exit_code, 0, passed.decision["blockers"])
            self.assertTrue(
                any(item["type"] == "reviewer_attestation" for item in passed.decision["evidence"])
            )

    def test_gate_attest_cli_writes_valid_manual_attestation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "package"
            shutil.copytree(EXAMPLE_PACKAGE, package)
            prepare_paper_candidate(package)
            before = root / "before.yaml"
            after = root / "after.yaml"
            before.write_text("stage: review_research\n", encoding="utf-8")
            after.write_text("stage: research_gate\n", encoding="utf-8")
            output = package / "reviewer_attestation.research_gate.json"
            with (
                patch.dict("os.environ", {ATTESTATION_KEY_ENV: KEY}),
                redirect_stdout(io.StringIO()) as stdout,
            ):
                exit_code = cli_main(
                    [
                        "gate",
                        "attest",
                        str(package),
                        "--gate",
                        "research_gate",
                        "--reviewer",
                        "independent-auditor",
                        "--principal-type",
                        "human",
                        "--provider",
                        "human",
                        "--model",
                        "manual-review",
                        "--run-id",
                        "review-1",
                        "--author-provider",
                        "codex",
                        "--reviewer-provider",
                        "human",
                        "--state-before",
                        str(before),
                        "--state-after",
                        str(after),
                        "--task-evidence",
                        str(package / "findings.json"),
                        "--output",
                        str(output),
                        "--format",
                        "json",
                    ]
                )
            envelope = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0, envelope)
            self.assertEqual(envelope["status"], "complete")
            with patch.dict("os.environ", {ATTESTATION_KEY_ENV: KEY}):
                evaluation = evaluate_gate(
                    package,
                    gate="research_gate",
                    reviewer="independent-auditor",
                )
            self.assertEqual(evaluation.exit_code, 0, evaluation.decision["blockers"])


if __name__ == "__main__":
    unittest.main()

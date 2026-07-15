from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from the_pass.attestation import (
    SIGNING_KEY_ENV,
    AttestationError,
    create_reviewer_attestation,
    create_reviewer_key_registry,
    generate_reviewer_keypair,
    registry_snapshot_path,
    verify_reviewer_attestation,
    write_registry_snapshot,
    write_reviewer_attestation,
)
from the_pass.cli import main as cli_main
from the_pass.gates import evaluate_gate, write_gate_decision
from the_pass.ledger import (
    append_gate_decision,
    append_ledger_entry,
    build_run_entry,
    verify_ledger_file,
)
from tests.test_validator import EXAMPLE_PACKAGE, prepare_paper_candidate


PRIVATE_KEY, PUBLIC_KEY = generate_reviewer_keypair()
LEGACY_KEY = "review-attestation-test-key-32-bytes-minimum"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def evidence() -> dict[str, str]:
    return {
        "state_before_sha256": hashlib.sha256(b"before").hexdigest(),
        "state_after_sha256": hashlib.sha256(b"after").hexdigest(),
        "stdout_sha256": EMPTY_SHA256,
        "stderr_sha256": EMPTY_SHA256,
        "task_sha256": hashlib.sha256(b"review task").hexdigest(),
    }


def registry(
    *,
    reviewer: str = "reviewer",
    principal_type: str = "provider",
    provider: str = "claude",
    revoked_at: str | None = None,
) -> dict:
    return create_reviewer_key_registry(
        registry_id="test-reviewer-keys",
        reviewer=reviewer,
        principal_type=principal_type,
        provider=provider,
        public_key=PUBLIC_KEY,
        created_at="2026-07-15T00:00:00Z",
        valid_from="2026-01-01T00:00:00Z",
        valid_until="2036-01-01T00:00:00Z",
        revoked_at=revoked_at,
    )


class ReviewerAttestationTests(unittest.TestCase):
    def test_v2_attestation_verifies_without_secret_and_tampering_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "reviewer_attestation.research_gate.json"
            public_registry = registry()
            write_registry_snapshot(
                registry_snapshot_path(root, "research_gate"), public_registry
            )
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
                private_key=PRIVATE_KEY,
                registry=public_registry,
                created_at="2026-07-15T00:00:00Z",
            )
            write_reviewer_attestation(path, document)
            with patch.dict(os.environ, {}, clear=True):
                _, blockers = verify_reviewer_attestation(
                    path,
                    gate="research_gate",
                    package_id="pkg_" + "a" * 24,
                    reviewer="reviewer",
                )
            self.assertEqual(blockers, [])

            _, wrong_package = verify_reviewer_attestation(
                path,
                gate="research_gate",
                package_id="pkg_" + "b" * 24,
                reviewer="reviewer",
            )
            self.assertIn("reviewer attestation package_id does not match", wrong_package)
            tampered = json.loads(path.read_text(encoding="utf-8"))
            tampered["principal"]["model"] = "changed"
            path.write_text(json.dumps(tampered), encoding="utf-8")
            _, blockers = verify_reviewer_attestation(
                path,
                gate="research_gate",
                package_id="pkg_" + "a" * 24,
                reviewer="reviewer",
            )
            self.assertIn("reviewer attestation signature does not verify", blockers)

    def test_legacy_hmac_is_readable_but_never_promotional(self) -> None:
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
                key=LEGACY_KEY,
                created_at="2026-07-15T00:00:00Z",
            )
            write_reviewer_attestation(path, document)
            loaded, blockers = verify_reviewer_attestation(
                path,
                gate="research_gate",
                package_id="pkg_" + "a" * 24,
                reviewer="reviewer",
            )
            self.assertEqual(loaded["schema_version"], 1)
            self.assertIn(
                "legacy HMAC reviewer attestation cannot authorize a new gate pass",
                blockers,
            )

    def test_automated_same_provider_and_revoked_key_are_rejected(self) -> None:
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
                private_key=PRIVATE_KEY,
                registry=registry(provider="codex"),
            )
        with self.assertRaisesRegex(AttestationError, "revoked"):
            create_reviewer_attestation(
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
                private_key=PRIVATE_KEY,
                registry=registry(revoked_at="2026-07-01T00:00:00Z"),
                created_at="2026-07-15T00:00:00Z",
            )

    def test_gate_pass_requires_matching_v2_attestation_and_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            package = Path(tmp) / "package"
            shutil.copytree(EXAMPLE_PACKAGE, package)
            prepare_paper_candidate(package)
            missing = evaluate_gate(
                package,
                gate="research_gate",
                reviewer="independent-auditor",
            )
            self.assertEqual(missing.exit_code, 2)
            public_registry = registry(reviewer="independent-auditor")
            write_registry_snapshot(
                registry_snapshot_path(package, "research_gate"), public_registry
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
                private_key=PRIVATE_KEY,
                registry=public_registry,
                created_at="2026-07-15T00:00:00Z",
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
                private_key=PRIVATE_KEY,
                registry=public_registry,
                created_at="2026-07-15T00:00:00Z",
            )
            write_reviewer_attestation(path, document)
            with patch.dict(os.environ, {}, clear=True):
                passed = evaluate_gate(
                    package,
                    gate="research_gate",
                    reviewer="independent-auditor",
                )
            self.assertEqual(passed.exit_code, 0, passed.decision["blockers"])
            evidence_types = {item["type"] for item in passed.decision["evidence"]}
            self.assertTrue(
                {"reviewer_attestation", "reviewer_key_registry"} <= evidence_types
            )

            ledger = Path(tmp) / "receipts.jsonl"
            decision_path = package / "gate_decision.research_gate.json"
            append_ledger_entry(ledger, package)
            write_gate_decision(decision_path, passed.decision)
            append_gate_decision(ledger, decision_path)
            with patch.dict(os.environ, {}, clear=True):
                self.assertEqual(verify_ledger_file(ledger), [])

    def test_keygen_and_attest_cli_do_not_expose_private_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package = root / "package"
            shutil.copytree(EXAMPLE_PACKAGE, package)
            prepare_paper_candidate(package)
            private_path = root / "reviewer.key"
            registry_path = root / "reviewers.json"
            with redirect_stdout(io.StringIO()) as keygen_stdout:
                keygen_exit = cli_main(
                    [
                        "gate",
                        "keygen",
                        "--registry-id",
                        "manual-reviewers",
                        "--reviewer",
                        "independent-auditor",
                        "--principal-type",
                        "human",
                        "--provider",
                        "human",
                        "--created-at",
                        "2026-07-15T00:00:00Z",
                        "--valid-from",
                        "2026-01-01T00:00:00Z",
                        "--valid-until",
                        "2036-01-01T00:00:00Z",
                        "--private-key-output",
                        str(private_path),
                        "--registry-output",
                        str(registry_path),
                        "--format",
                        "json",
                    ]
                )
            private_value = private_path.read_text(encoding="ascii").strip()
            self.assertEqual(keygen_exit, 0)
            self.assertNotIn(private_value, keygen_stdout.getvalue())
            self.assertEqual(private_path.stat().st_mode & 0o777, 0o600)

            before = root / "before.yaml"
            after = root / "after.yaml"
            before.write_text("stage: review_research\n", encoding="utf-8")
            after.write_text("stage: research_gate\n", encoding="utf-8")
            output = package / "reviewer_attestation.research_gate.json"
            with (
                patch.dict(os.environ, {SIGNING_KEY_ENV: private_value}),
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
                        "--key-registry",
                        str(registry_path),
                        "--created-at",
                        "2026-07-15T00:00:00Z",
                        "--output",
                        str(output),
                        "--format",
                        "json",
                    ]
                )
            envelope = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0, envelope)
            self.assertNotIn(private_value, stdout.getvalue())
            with patch.dict(os.environ, {}, clear=True):
                evaluation = evaluate_gate(
                    package,
                    gate="research_gate",
                    reviewer="independent-auditor",
                )
            self.assertEqual(evaluation.exit_code, 0, evaluation.decision["blockers"])


if __name__ == "__main__":
    unittest.main()

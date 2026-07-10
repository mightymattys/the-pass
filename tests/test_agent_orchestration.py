from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from the_pass.agent_orchestration import (
    AgentSafetyError,
    _write_create_only,
    build_provider_argv,
    critical_paths_are_protected,
    dispatch_agent_task,
    inspect_agent_task,
    validate_agent_task_file,
)
from the_pass.validator import validate_artifact


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "fake_agent_provider.py"
REQUIRED_FORBIDDEN = [
    "gate_decision",
    "live_transaction",
    "credential_access",
    "permission_bypass",
    "recursive_cross_provider",
    "apply_patch",
    "git_commit",
    "git_push",
]


class AgentOrchestrationTests(unittest.TestCase):
    def task_document(
        self,
        *,
        caller: str = "codex",
        target: str = "claude",
        role: str = "reviewer",
        mode: str = "read_only",
        objective: str = "Review README and report findings.",
        allowed: list[str] | None = None,
        timeout: int = 5,
        output_bytes: int = 65536,
    ) -> dict:
        return {
            "schema_version": 1,
            "task_id": "fixture-agent-task",
            "created_at": "2026-07-10T00:00:00Z",
            "caller_provider": caller,
            "target_provider": target,
            "role": role,
            "objective": objective,
            "acceptance_criteria": ["Return schema-valid evidence."],
            "workspace_root": ".",
            "input_paths": ["README.md"],
            "mode": mode,
            "allowed_write_paths": allowed or [],
            "timeout_seconds": timeout,
            "max_output_bytes": output_bytes,
            "max_budget_usd": 1.0,
            "allow_native_subagents": False,
            "forbidden_actions": REQUIRED_FORBIDDEN,
        }

    def write_task(self, root: Path, document: dict) -> Path:
        path = root / "agent-task.yaml"
        path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
        return path

    def fixture_commands(self) -> dict[str, list[str]]:
        return {
            "codex": [sys.executable, str(FIXTURE), "codex"],
            "claude": [sys.executable, str(FIXTURE), "claude"],
        }

    def git_repo(self, root: Path) -> None:
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "fixture@example.com"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "Fixture"], cwd=root, check=True)
        (root / "README.md").write_text("fixture\n", encoding="utf-8")
        subprocess.run(["git", "add", "README.md"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "fixture"], cwd=root, check=True)

    def test_artifacts_and_critical_path_inventory_validate(self) -> None:
        for name in ("agent_task", "agent_result", "agent_run"):
            result = validate_artifact(ROOT / "templates" / f"{name}.yaml", artifact_type=name)
            self.assertTrue(result.ok, result.issues)
        self.assertTrue(critical_paths_are_protected())
        policy = yaml.safe_load((ROOT / "config" / "agent-orchestration.v1.yaml").read_text())
        allowed_env = {
            name
            for provider in policy["providers"].values()
            for name in provider["allowed_env_names"]
        }
        self.assertNotIn("OPENAI_API_KEY", allowed_env)
        self.assertNotIn("ANTHROPIC_API_KEY", allowed_env)
        result_schema = json.loads((ROOT / "schemas" / "agent_result.schema.json").read_text())
        self.assertEqual(result_schema["properties"]["schema_version"]["type"], "integer")
        self.assertEqual(result_schema["properties"]["status"]["type"], "string")
        self.assertEqual(
            result_schema["properties"]["findings"]["items"]["properties"]["severity"]["type"],
            "string",
        )
        provider_schema = ROOT / "schemas" / "agent_result.provider.schema.json"
        packaged_provider_schema = (
            ROOT / "src" / "the_pass" / "schemas" / "agent_result.provider.schema.json"
        )
        self.assertEqual(provider_schema.read_bytes(), packaged_provider_schema.read_bytes())
        provider_text = provider_schema.read_text(encoding="utf-8")
        self.assertNotIn("uniqueItems", provider_text)
        self.assertNotIn("maxItems", provider_text)

    def test_both_provider_argv_are_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            for caller, target in (("codex", "claude"), ("claude", "codex")):
                with self.subTest(target=target):
                    task_path = self.write_task(root, self.task_document(caller=caller, target=target))
                    context = validate_agent_task_file(task_path)
                    argv = build_provider_argv(
                        context,
                        execution_root=root,
                        result_path=root / "result.json",
                        provider_commands=self.fixture_commands(),
                    )
                    joined = " ".join(argv)
                    self.assertNotIn("dangerously", joined)
                    self.assertNotIn("--add-dir", argv)
                    self.assertIn("read-only" if target == "codex" else "plan", argv)

    def test_cross_provider_native_subagents_are_read_only_specialists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            document = self.task_document(role="reviewer")
            document["allow_native_subagents"] = True
            context = validate_agent_task_file(self.write_task(root, document))
            argv = build_provider_argv(
                context,
                execution_root=root,
                result_path=root / "result.json",
                provider_commands=self.fixture_commands(),
            )
            self.assertIn("Read,Glob,Grep,Agent(researcher),Agent(reviewer)", argv)
            self.assertIn("Write,Edit,Bash,Agent(implementer),Agent(coordinator)", argv)
            self.assertNotIn("Read,Glob,Grep,Agent", argv)

    def test_inspect_is_non_executing_and_depth_is_runtime_derived(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            task_path = self.write_task(root, self.task_document())
            document = inspect_agent_task(task_path, environment={"THE_PASS_AGENT_DEPTH": "0"})
            self.assertFalse(document["would_execute"])
            self.assertEqual(document["runtime_depth"], 0)
            with self.assertRaisesRegex(AgentSafetyError, "depth"):
                dispatch_agent_task(
                    task_path,
                    output_dir=root / "runs",
                    execute=True,
                    environment={"THE_PASS_AGENT_DEPTH": "1"},
                    provider_commands=self.fixture_commands(),
                )

    def test_forbidden_objective_and_role_mode_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            forbidden = self.write_task(
                root,
                self.task_document(objective="Place a live order after loading an API key."),
            )
            with self.assertRaisesRegex(AgentSafetyError, "forbidden safety pattern"):
                validate_agent_task_file(forbidden)
            invalid_mode = self.task_document(role="reviewer", mode="worktree_patch", allowed=["docs"])
            with self.assertRaisesRegex(AgentSafetyError, "cannot use mode"):
                validate_agent_task_file(self.write_task(root, invalid_mode))

    def test_path_traversal_symlink_and_budget_limits_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            traversal = self.task_document()
            traversal["input_paths"] = ["../outside.txt"]
            with self.assertRaisesRegex(AgentSafetyError, "escapes the workspace"):
                validate_agent_task_file(self.write_task(root, traversal))

            outside = root.parent / f"{root.name}-outside"
            outside.mkdir()
            try:
                (root / "generated").symlink_to(outside, target_is_directory=True)
                symlink = self.task_document(
                    caller="claude",
                    target="codex",
                    role="implementer",
                    mode="worktree_patch",
                    allowed=["generated"],
                )
                with self.assertRaisesRegex(AgentSafetyError, "uses a symlink"):
                    validate_agent_task_file(self.write_task(root, symlink))
            finally:
                outside.rmdir()

            budget = self.task_document()
            budget["max_budget_usd"] = 5.01
            with self.assertRaisesRegex(AgentSafetyError, "budget exceeds"):
                validate_agent_task_file(self.write_task(root, budget))

    def test_fixture_dispatch_succeeds_in_both_directions(self) -> None:
        for caller, target in (("codex", "claude"), ("claude", "codex")):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "README.md").write_text("fixture\n", encoding="utf-8")
                task_path = self.write_task(root, self.task_document(caller=caller, target=target))
                run, run_path, exit_code = dispatch_agent_task(
                    task_path,
                    output_dir=root / "runs",
                    execute=True,
                    provider_commands=self.fixture_commands(),
                )
                self.assertEqual(exit_code, 0)
                self.assertEqual(run["status"], "complete")
                self.assertEqual(run["limits"]["attempts"], 1)
                self.assertTrue(validate_artifact(run_path, artifact_type="agent_run").ok)
                self.assertIsNotNone(run["metadata"]["session_id"])

    def test_claude_single_fenced_json_fallback_is_validated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            task_path = self.write_task(root, self.task_document(objective="fenced-result"))
            run, run_path, exit_code = dispatch_agent_task(
                task_path,
                output_dir=root / "runs",
                execute=True,
                provider_commands=self.fixture_commands(),
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(run["status"], "complete")
            self.assertTrue(validate_artifact(run_path, artifact_type="agent_run").ok)

    def test_blocked_result_uses_stable_semantic_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            task_path = self.write_task(root, self.task_document(objective="Return blocked-result evidence."))
            run, _, exit_code = dispatch_agent_task(
                task_path,
                output_dir=root / "runs",
                execute=True,
                provider_commands=self.fixture_commands(),
            )
            self.assertEqual(exit_code, 2)
            self.assertEqual(run["status"], "blocked")

    def test_worktree_patch_never_changes_caller_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.git_repo(root)
            task_path = self.write_task(
                root,
                self.task_document(
                    caller="claude",
                    target="codex",
                    role="implementer",
                    mode="worktree_patch",
                    objective="Create the bounded fixture file.",
                    allowed=["generated"],
                ),
            )
            run, _, exit_code = dispatch_agent_task(
                task_path,
                output_dir=root / "runs",
                execute=True,
                provider_commands=self.fixture_commands(),
            )
            self.assertEqual(exit_code, 0)
            self.assertFalse((root / "generated").exists())
            self.assertEqual(run["patch"]["changed_paths"], ["generated/agent.txt"])
            patch = Path(run["patch"]["path"])
            self.assertIn("generated by fixture", patch.read_text(encoding="utf-8"))
            worktrees = subprocess.run(
                ["git", "worktree", "list", "--porcelain"], cwd=root, check=True, capture_output=True, text=True
            ).stdout
            self.assertEqual(worktrees.count("worktree "), 1)

    def test_protected_and_out_of_scope_changes_are_forbidden(self) -> None:
        for objective, expected in (
            ("Make a protected-change.", "protected path"),
            ("Make an out-of-scope-change.", "outside allowed scope"),
        ):
            with self.subTest(objective=objective), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.git_repo(root)
                task_path = self.write_task(
                    root,
                    self.task_document(
                        caller="claude",
                        target="codex",
                        role="implementer",
                        mode="worktree_patch",
                        objective=objective,
                        allowed=["generated"],
                    ),
                )
                run, _, exit_code = dispatch_agent_task(
                    task_path,
                    output_dir=root / "runs",
                    execute=True,
                    provider_commands=self.fixture_commands(),
                )
                self.assertEqual(exit_code, 3)
                self.assertEqual(run["status"], "forbidden")
                self.assertIn(expected, run["issues"][0])
                self.assertIsNone(run["patch"])

    def test_timeout_output_limit_and_provider_error_write_failed_receipts(self) -> None:
        cases = (
            ("sleep-provider", 1, 65536, "timed out"),
            ("excess-output", 5, 1024, "exceeded"),
            ("provider-error", 5, 65536, "exited with code 9"),
        )
        for objective, timeout, output_bytes, expected in cases:
            with self.subTest(objective=objective), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "README.md").write_text("fixture\n", encoding="utf-8")
                task_path = self.write_task(
                    root,
                    self.task_document(
                        objective=objective,
                        timeout=timeout,
                        output_bytes=output_bytes,
                    ),
                )
                run, run_path, exit_code = dispatch_agent_task(
                    task_path,
                    output_dir=root / "runs",
                    execute=True,
                    provider_commands=self.fixture_commands(),
                )
                self.assertEqual(exit_code, 1)
                self.assertEqual(run["status"], "failed")
                self.assertIn(expected, run["issues"][0])
                self.assertTrue(validate_artifact(run_path, artifact_type="agent_run").ok)
                if objective == "provider-error":
                    self.assertNotEqual(
                        run["streams"]["stderr_sha256"], hashlib.sha256(b"").hexdigest()
                    )
                self.assertEqual(run["limits"]["attempts"], 1)

    def test_structured_provider_failure_metadata_is_preserved_without_raw_logs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            task_path = self.write_task(
                root,
                self.task_document(objective="structured-provider-error"),
            )
            run, _, exit_code = dispatch_agent_task(
                task_path,
                output_dir=root / "runs",
                execute=True,
                provider_commands=self.fixture_commands(),
            )
            self.assertEqual(exit_code, 1)
            self.assertIn("subtype=error_max_budget_usd", run["issues"][0])
            self.assertEqual(run["metadata"]["session_id"], "fixture-failed-session")
            self.assertEqual(run["metadata"]["cost_usd"], 0.25)

    def test_malformed_results_fail_closed_in_both_directions(self) -> None:
        cases = (("codex", "claude", "Expecting value"), ("claude", "codex", "structured result"))
        for caller, target, expected in cases:
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "README.md").write_text("fixture\n", encoding="utf-8")
                task_path = self.write_task(
                    root,
                    self.task_document(
                        caller=caller,
                        target=target,
                        objective="malformed-result",
                    ),
                )
                run, run_path, exit_code = dispatch_agent_task(
                    task_path,
                    output_dir=root / "runs",
                    execute=True,
                    provider_commands=self.fixture_commands(),
                )
                self.assertEqual(exit_code, 1)
                self.assertEqual(run["status"], "failed")
                self.assertIn(expected, run["issues"][0])
                self.assertTrue(validate_artifact(run_path, artifact_type="agent_run").ok)

    def test_result_identity_evidence_and_read_only_claims_fail_closed(self) -> None:
        cases = (
            ("wrong-task", "task_id does not match"),
            ("missing-evidence", "evidence path does not exist"),
            ("readonly-change-claim", "read-only provider result claims changed paths"),
        )
        for objective, expected in cases:
            with self.subTest(objective=objective), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "README.md").write_text("fixture\n", encoding="utf-8")
                task_path = self.write_task(root, self.task_document(objective=objective))
                run, _, exit_code = dispatch_agent_task(
                    task_path,
                    output_dir=root / "runs",
                    execute=True,
                    provider_commands=self.fixture_commands(),
                )
                self.assertIn(exit_code, (1, 3))
                self.assertIn(expected, run["issues"][0])

    def test_codex_structured_result_file_obeys_output_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            task_path = self.write_task(
                root,
                self.task_document(
                    caller="claude",
                    target="codex",
                    objective="oversized-structured-result",
                    output_bytes=1024,
                ),
            )
            run, _, exit_code = dispatch_agent_task(
                task_path,
                output_dir=root / "runs",
                execute=True,
                provider_commands=self.fixture_commands(),
            )
            self.assertEqual(exit_code, 1)
            self.assertIn("structured result exceeded", run["issues"][0])

    def test_oversized_patch_fails_and_worktree_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.git_repo(root)
            task_path = self.write_task(
                root,
                self.task_document(
                    caller="claude",
                    target="codex",
                    role="implementer",
                    mode="worktree_patch",
                    objective="Create an oversized-patch fixture.",
                    allowed=["generated"],
                    output_bytes=1024,
                ),
            )
            run, _, exit_code = dispatch_agent_task(
                task_path,
                output_dir=root / "runs",
                execute=True,
                provider_commands=self.fixture_commands(),
            )
            self.assertEqual(exit_code, 1)
            self.assertIn("patch exceeded", run["issues"][0])
            self.assertFalse((root / "generated").exists())
            worktrees = subprocess.run(
                ["git", "worktree", "list", "--porcelain"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            self.assertEqual(worktrees.count("worktree "), 1)

    def test_concurrent_worktree_runs_are_isolated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.git_repo(root)

            def run_task(index: int) -> tuple[dict, Path, int]:
                document = self.task_document(
                    caller="claude",
                    target="codex",
                    role="implementer",
                    mode="worktree_patch",
                    objective=f"Create bounded fixture file {index}.",
                    allowed=[f"generated-{index}"],
                )
                document["task_id"] = f"fixture-agent-task-{index}"
                task_path = root / f"agent-task-{index}.yaml"
                task_path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
                return dispatch_agent_task(
                    task_path,
                    output_dir=root / "runs",
                    execute=True,
                    provider_commands=self.fixture_commands(),
                )

            with ThreadPoolExecutor(max_workers=2) as pool:
                completed = list(pool.map(run_task, (1, 2)))

            self.assertEqual([item[2] for item in completed], [0, 0])
            patch_paths = [item[0]["patch"]["path"] for item in completed]
            self.assertEqual(len(set(patch_paths)), 2)
            self.assertFalse((root / "generated-1").exists())
            self.assertFalse((root / "generated-2").exists())
            worktrees = subprocess.run(
                ["git", "worktree", "list", "--porcelain"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            self.assertEqual(worktrees.count("worktree "), 1)

    def test_create_only_receipts_cannot_be_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "receipt.json"
            _write_create_only(path, b"first\n")
            with self.assertRaises(FileExistsError):
                _write_create_only(path, b"second\n")
            self.assertEqual(path.read_bytes(), b"first\n")

    def test_agent_run_embedded_result_and_fingerprint_are_semantic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            task_path = self.write_task(root, self.task_document())
            run, run_path, exit_code = dispatch_agent_task(
                task_path,
                output_dir=root / "runs",
                execute=True,
                provider_commands=self.fixture_commands(),
            )
            self.assertEqual(exit_code, 0)
            run["result"]["summary"] = "tampered"
            run_path.write_text(json.dumps(run), encoding="utf-8")
            validation = validate_artifact(run_path, artifact_type="agent_run")
            self.assertFalse(validation.ok)
            self.assertTrue(
                any(issue.path == "$.result_fingerprint" for issue in validation.issues)
            )

    def test_child_environment_depth_does_not_trust_task_or_parent_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("fixture\n", encoding="utf-8")
            task_path = self.write_task(root, self.task_document())
            original = os.environ.get("THE_PASS_AGENT_DEPTH")
            try:
                os.environ["THE_PASS_AGENT_DEPTH"] = "1"
                with self.assertRaisesRegex(AgentSafetyError, "depth"):
                    dispatch_agent_task(
                        task_path,
                        output_dir=root / "runs",
                        execute=True,
                        provider_commands=self.fixture_commands(),
                    )
            finally:
                if original is None:
                    os.environ.pop("THE_PASS_AGENT_DEPTH", None)
                else:
                    os.environ["THE_PASS_AGENT_DEPTH"] = original


if __name__ == "__main__":
    unittest.main()

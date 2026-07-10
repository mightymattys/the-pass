"""Bounded, provider-neutral delegation to local Codex and Claude Code CLIs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Mapping, Sequence

import yaml

from .validator import load_document, repo_root_from, validate_artifact


DEPTH_ENV = "THE_PASS_AGENT_DEPTH"
PARENT_RUN_ENV = "THE_PASS_AGENT_PARENT_RUN"
PACKAGED_POLICY_PATH = Path(__file__).resolve().parent / "policies" / "agent-orchestration.v1.yaml"
PACKAGED_RESULT_SCHEMA = Path(__file__).resolve().parent / "schemas" / "agent_result.schema.json"
PACKAGED_PROVIDER_RESULT_SCHEMA = (
    Path(__file__).resolve().parent / "schemas" / "agent_result.provider.schema.json"
)


class AgentOrchestrationError(ValueError):
    """Raised for invalid tasks, provider failures, or malformed results."""


class AgentSafetyError(AgentOrchestrationError):
    """Raised when delegation crosses a mechanical safety boundary."""


@dataclass(frozen=True)
class TaskContext:
    task: dict[str, Any]
    workspace_root: Path
    input_paths: tuple[Path, ...]
    allowed_write_paths: tuple[str, ...]
    runtime_depth: int
    policy: dict[str, Any]


@dataclass(frozen=True)
class ProcessOutcome:
    returncode: int | None
    stdout: bytes
    stderr: bytes
    stdout_sha256: str
    stderr_sha256: str
    output_exceeded: bool
    timed_out: bool
    duration_ms: int


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_yaml(path: Path) -> dict[str, Any]:
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise AgentOrchestrationError(f"policy must be an object: {path}")
    return document


def load_agent_policy() -> dict[str, Any]:
    """Load the packaged policy and reject source-checkout drift."""

    if not PACKAGED_POLICY_PATH.is_file():
        raise AgentOrchestrationError("packaged agent orchestration policy is missing")
    packaged = PACKAGED_POLICY_PATH.read_bytes()
    root = repo_root_from(Path.cwd())
    source = root / "config" / "agent-orchestration.v1.yaml"
    if source.is_file() and source.read_bytes() != packaged:
        raise AgentSafetyError("source and packaged agent orchestration policies differ")
    policy = _load_yaml(PACKAGED_POLICY_PATH)
    required = {
        "schema_version",
        "interface_version",
        "limits",
        "providers",
        "roles",
        "required_forbidden_actions",
        "forbidden_objective_patterns",
        "protected_paths",
        "critical_authority_paths",
        "safety",
    }
    if not required <= set(policy):
        raise AgentOrchestrationError("agent orchestration policy is incomplete")
    if policy["schema_version"] != 1:
        raise AgentOrchestrationError("unsupported agent orchestration policy version")
    if set(policy["providers"]) != {"codex", "claude"}:
        raise AgentOrchestrationError("agent orchestration policy must define codex and claude")
    if policy["limits"].get("attempts") != 1:
        raise AgentSafetyError("external provider attempts must remain one")
    safety = policy["safety"]
    required_false = {
        "provider_retryable",
        "auto_apply_patch",
        "gate_decision_write_allowed",
        "live_code_write_allowed",
        "shell_execution_allowed",
        "task_text_scanner_is_authoritative",
    }
    if any(safety.get(name) is not False for name in required_false):
        raise AgentSafetyError("agent orchestration safety flags must remain false")
    return policy


def _relative_path(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AgentOrchestrationError(f"{label} must be a non-empty relative path")
    normalized = value.replace("\\", "/")
    pure = PurePosixPath(normalized)
    if pure.is_absolute() or ".." in pure.parts:
        raise AgentSafetyError(f"{label} escapes the workspace: {value}")
    collapsed = pure.as_posix()
    if collapsed in {"", "."}:
        raise AgentSafetyError(f"{label} must identify a workspace entry")
    return collapsed


def _inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise AgentSafetyError(f"path escapes workspace: {relative}") from exc
    return path


def _path_matches(path: str, prefix: str) -> bool:
    return path == prefix or path.startswith(prefix.rstrip("/") + "/")


def _path_uses_symlink(root: Path, relative: str) -> bool:
    current = root
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink():
            return True
        if not current.exists():
            return False
    return False


def _runtime_depth(environment: Mapping[str, str] | None = None) -> int:
    raw = (environment or os.environ).get(DEPTH_ENV, "0")
    try:
        depth = int(raw)
    except (TypeError, ValueError) as exc:
        raise AgentSafetyError(f"{DEPTH_ENV} must be an integer") from exc
    if depth < 0:
        raise AgentSafetyError(f"{DEPTH_ENV} cannot be negative")
    return depth


def _forbidden_objective(task: Mapping[str, Any], policy: Mapping[str, Any]) -> str | None:
    text = "\n".join(
        [str(task.get("objective", "")), *[str(value) for value in task.get("acceptance_criteria", [])]]
    )
    for pattern in policy["forbidden_objective_patterns"]:
        if re.search(str(pattern), text, flags=re.IGNORECASE):
            return str(pattern)
    return None


def validate_agent_task_file(
    task_path: Path,
    *,
    environment: Mapping[str, str] | None = None,
) -> TaskContext:
    """Validate an AgentTask and resolve its bounded workspace context."""

    task_path = task_path.resolve()
    validation = validate_artifact(task_path, artifact_type="agent_task")
    if not validation.ok:
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in validation.issues)
        raise AgentOrchestrationError(f"agent task is invalid: {details}")
    task = load_document(task_path)
    if not isinstance(task, dict):
        raise AgentOrchestrationError("agent task must be an object")
    policy = load_agent_policy()
    caller = task["caller_provider"]
    target = task["target_provider"]
    if caller == target:
        raise AgentOrchestrationError("caller_provider and target_provider must differ")
    role_policy = policy["roles"].get(task["role"])
    if not isinstance(role_policy, dict) or task["mode"] not in role_policy.get("modes", []):
        raise AgentSafetyError(f"role {task['role']} cannot use mode {task['mode']}")
    if task["allow_native_subagents"] and target not in role_policy.get("native_subagents", []):
        raise AgentSafetyError(
            f"native subagents are not supported for {task['role']} on {target}"
        )
    if task["allow_native_subagents"] and task["mode"] != "read_only":
        raise AgentSafetyError("cross-provider native subagents are read-only in v1")

    limits = policy["limits"]
    if task["timeout_seconds"] > limits["max_timeout_seconds"]:
        raise AgentSafetyError("task timeout exceeds policy maximum")
    if task["max_output_bytes"] > limits["max_output_bytes"]:
        raise AgentSafetyError("task output limit exceeds policy maximum")
    if float(task["max_budget_usd"]) > float(limits["max_budget_usd"]):
        raise AgentSafetyError("task budget exceeds policy maximum")
    required_forbidden = set(policy["required_forbidden_actions"])
    if not required_forbidden <= set(task["forbidden_actions"]):
        missing = ", ".join(sorted(required_forbidden - set(task["forbidden_actions"])))
        raise AgentSafetyError(f"agent task is missing forbidden actions: {missing}")
    forbidden_pattern = _forbidden_objective(task, policy)
    if forbidden_pattern is not None:
        raise AgentSafetyError(
            f"agent task objective matches forbidden safety pattern: {forbidden_pattern}"
        )

    workspace_value = Path(task["workspace_root"])
    workspace_root = (
        workspace_value.resolve()
        if workspace_value.is_absolute()
        else (task_path.parent / workspace_value).resolve()
    )
    if not workspace_root.is_dir():
        raise AgentOrchestrationError(f"workspace_root is not a directory: {workspace_root}")
    inputs = []
    for value in task["input_paths"]:
        relative = _relative_path(value, label="input_path")
        path = _inside(workspace_root, relative)
        if not path.exists():
            raise AgentOrchestrationError(f"input path does not exist: {relative}")
        inputs.append(path)
    allowed = tuple(
        _relative_path(value, label="allowed_write_path")
        for value in task["allowed_write_paths"]
    )
    if task["mode"] == "read_only" and allowed:
        raise AgentSafetyError("read_only tasks cannot declare allowed_write_paths")
    if task["mode"] == "worktree_patch" and not allowed:
        raise AgentSafetyError("worktree_patch tasks require allowed_write_paths")
    protected = tuple(str(value) for value in policy["protected_paths"])
    for relative in allowed:
        if any(_path_matches(relative, item) or _path_matches(item, relative) for item in protected):
            raise AgentSafetyError(f"allowed write path intersects protected path: {relative}")
        if _path_uses_symlink(workspace_root, relative):
            raise AgentSafetyError(f"allowed write path uses a symlink: {relative}")

    return TaskContext(
        task=task,
        workspace_root=workspace_root,
        input_paths=tuple(inputs),
        allowed_write_paths=allowed,
        runtime_depth=_runtime_depth(environment),
        policy=policy,
    )


def _result_schema() -> dict[str, Any]:
    return json.loads(PACKAGED_PROVIDER_RESULT_SCHEMA.read_text(encoding="utf-8"))


def _plugin_root(workspace_root: Path) -> Path | None:
    for candidate in (workspace_root, *workspace_root.parents):
        if (candidate / ".claude-plugin" / "plugin.json").is_file() and (
            candidate / "skills"
        ).is_dir():
            return candidate
    root = repo_root_from(Path(__file__).resolve())
    if (root / ".claude-plugin" / "plugin.json").is_file():
        return root
    return None


def _provider_prefix(
    provider: str,
    policy: Mapping[str, Any],
    provider_commands: Mapping[str, Sequence[str]] | None,
) -> list[str]:
    if provider_commands and provider in provider_commands:
        prefix = [str(value) for value in provider_commands[provider]]
        if not prefix:
            raise AgentOrchestrationError(f"empty provider command for {provider}")
        return prefix
    binary_name = str(policy["providers"][provider]["binary"])
    binary = shutil.which(binary_name)
    if binary is None:
        raise AgentOrchestrationError(f"provider binary is not installed: {binary_name}")
    return [binary]


def build_provider_argv(
    context: TaskContext,
    *,
    execution_root: Path,
    result_path: Path,
    provider_commands: Mapping[str, Sequence[str]] | None = None,
) -> list[str]:
    """Build one provider argv without executing it."""

    task = context.task
    provider = task["target_provider"]
    prefix = _provider_prefix(provider, context.policy, provider_commands)
    if provider == "codex":
        sandbox = "read-only" if task["mode"] == "read_only" else "workspace-write"
        argv = [
            *prefix,
            "exec",
            "--ephemeral",
            "--json",
            "--color",
            "never",
            "--sandbox",
            sandbox,
            "--cd",
            str(execution_root),
            "--output-schema",
            str(PACKAGED_PROVIDER_RESULT_SCHEMA),
            "--output-last-message",
            str(result_path),
            "-",
        ]
    else:
        argv = [
            *prefix,
            "-p",
            "--output-format",
            "json",
            "--no-session-persistence",
            "--json-schema",
            json.dumps(_result_schema(), sort_keys=True, separators=(",", ":")),
            "--max-budget-usd",
            str(task["max_budget_usd"]),
        ]
        plugin_root = _plugin_root(context.workspace_root)
        if plugin_root is not None:
            argv.extend(["--plugin-dir", str(plugin_root)])
        if task["allow_native_subagents"]:
            if plugin_root is None:
                raise AgentSafetyError("native subagents require the The Pass Claude plugin root")
            argv.extend(
                [
                    "--agent",
                    "the-pass:coordinator",
                    "--permission-mode",
                    "plan",
                    "--tools",
                    "Read,Glob,Grep,Agent(researcher),Agent(reviewer)",
                    "--disallowedTools",
                    "Write,Edit,Bash,Agent(implementer),Agent(coordinator)",
                ]
            )
        elif task["mode"] == "read_only":
            argv.extend(
                [
                    "--permission-mode",
                    "plan",
                    "--tools",
                    "Read,Glob,Grep",
                    "--disallowedTools",
                    "Write,Edit,Bash,Agent",
                ]
            )
        else:
            argv.extend(
                [
                    "--permission-mode",
                    "acceptEdits",
                    "--tools",
                    "Read,Glob,Grep,Edit,Write",
                    "--disallowedTools",
                    "Bash,Agent",
                ]
            )
    forbidden = set(context.policy["providers"][provider]["forbidden_flags"])
    if any(value in forbidden for value in argv):
        raise AgentSafetyError(f"provider argv contains a forbidden flag for {provider}")
    return argv


def _sanitize_argv(argv: Sequence[str]) -> list[str]:
    sanitized: list[str] = []
    redact_next = False
    for value in argv:
        if redact_next:
            sanitized.append("<structured-output-schema>")
            redact_next = False
            continue
        sanitized.append(value)
        if value == "--json-schema":
            redact_next = True
    return sanitized


def _build_prompt(context: TaskContext) -> str:
    task_json = json.dumps(context.task, indent=2, sort_keys=True)
    result_shape = {
        "schema_version": 1,
        "task_id": context.task["task_id"],
        "status": "complete|blocked|failed",
        "summary": "concise result",
        "findings": [],
        "changed_paths": [],
        "next_actions": [],
        "assumptions": [],
        "issues": [],
    }
    return (
        "Execute exactly one bounded The Pass agent task. Return only a JSON object matching "
        "AgentResult v1. The object must contain exactly these top-level keys and no others:\n"
        + json.dumps(result_shape, indent=2, sort_keys=True)
        + "\nDo not return AgentTask, AgentRun, provider, budget, timing, or caller metadata. "
        "Do not invoke another external AI provider, access credentials, change "
        "gate decisions, approve live trading, commit, push, or apply a patch. Respect the role, "
        "mode, input paths, and acceptance criteria. Evidence paths and changed paths must be "
        "repository-relative.\n\nAgentTask:\n"
        + task_json
        + "\n"
    )


def _child_environment(context: TaskContext, run_id: str) -> dict[str, str]:
    provider = context.task["target_provider"]
    allowed = set(context.policy["providers"][provider]["allowed_env_names"])
    child = {name: value for name, value in os.environ.items() if name in allowed}
    child[DEPTH_ENV] = str(context.runtime_depth + 1)
    child[PARENT_RUN_ENV] = run_id
    return child


def _terminate(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        try:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
        except OSError:
            pass
        process.wait()


def _run_bounded_process(
    argv: Sequence[str],
    *,
    prompt: str,
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: int,
    max_output_bytes: int,
) -> ProcessOutcome:
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="the-pass-agent-io-") as temporary:
        root = Path(temporary)
        stdin_path = root / "stdin.txt"
        stdout_path = root / "stdout.bin"
        stderr_path = root / "stderr.bin"
        stdin_path.write_text(prompt, encoding="utf-8")
        with stdin_path.open("rb") as stdin, stdout_path.open("wb") as stdout, stderr_path.open(
            "wb"
        ) as stderr:
            process = subprocess.Popen(
                list(argv),
                cwd=cwd,
                env=dict(environment),
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                shell=False,
                start_new_session=os.name != "nt",
            )
            timed_out = False
            output_exceeded = False
            while process.poll() is None:
                elapsed = time.monotonic() - started
                output_size = stdout_path.stat().st_size + stderr_path.stat().st_size
                if output_size > max_output_bytes:
                    output_exceeded = True
                    _terminate(process)
                    break
                if elapsed > timeout_seconds:
                    timed_out = True
                    _terminate(process)
                    break
                time.sleep(0.05)
            returncode = process.poll()
        stdout_bytes = stdout_path.read_bytes()
        stderr_bytes = stderr_path.read_bytes()
        if len(stdout_bytes) + len(stderr_bytes) > max_output_bytes:
            output_exceeded = True
        duration_ms = int((time.monotonic() - started) * 1000)
        return ProcessOutcome(
            returncode=returncode,
            stdout=stdout_bytes[:max_output_bytes],
            stderr=stderr_bytes[:max_output_bytes],
            stdout_sha256=_sha256_bytes(stdout_bytes),
            stderr_sha256=_sha256_bytes(stderr_bytes),
            output_exceeded=output_exceeded,
            timed_out=timed_out,
            duration_ms=duration_ms,
        )


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, check=False, shell=False
    )
    if check and result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise AgentOrchestrationError(f"git {' '.join(args)} failed: {message}")
    return result


@contextmanager
def _execution_workspace(
    context: TaskContext, run_id: str
) -> Iterator[tuple[Path, str]]:
    if context.task["mode"] == "read_only":
        yield context.workspace_root, "source_read_only"
        return
    top_level = _git(context.workspace_root, "rev-parse", "--show-toplevel").stdout
    git_root = Path(top_level.decode("utf-8").strip()).resolve()
    if git_root != context.workspace_root:
        raise AgentSafetyError("worktree_patch workspace_root must be the git repository root")
    temporary = Path(
        tempfile.mkdtemp(prefix=f"the-pass-{context.task['task_id']}-{run_id[-8:]}-")
    )
    worktree = temporary / "workspace"
    try:
        _git(git_root, "worktree", "add", "--detach", str(worktree), "HEAD")
        yield worktree, "detached_worktree"
    finally:
        _git(git_root, "worktree", "remove", "--force", str(worktree), check=False)
        _git(git_root, "worktree", "prune", check=False)
        shutil.rmtree(temporary, ignore_errors=True)


def _changed_paths(worktree: Path) -> list[str]:
    tracked = _git(worktree, "diff", "--name-only", "-z", "HEAD").stdout
    untracked = _git(worktree, "ls-files", "--others", "--exclude-standard", "-z").stdout
    values = {
        value.decode("utf-8")
        for value in tracked.split(b"\0") + untracked.split(b"\0")
        if value
    }
    return sorted(values)


def _validate_changed_paths(context: TaskContext, changed_paths: Sequence[str]) -> None:
    protected = [str(value) for value in context.policy["protected_paths"]]
    for path in changed_paths:
        normalized = _relative_path(path, label="changed_path")
        if any(_path_matches(normalized, prefix) for prefix in protected):
            raise AgentSafetyError(f"agent changed protected path: {normalized}")
        if not any(_path_matches(normalized, prefix) for prefix in context.allowed_write_paths):
            raise AgentSafetyError(f"agent changed path outside allowed scope: {normalized}")


def _build_patch(worktree: Path, changed_paths: Sequence[str]) -> bytes:
    untracked = _git(worktree, "ls-files", "--others", "--exclude-standard", "-z").stdout
    untracked_paths = [
        value.decode("utf-8") for value in untracked.split(b"\0") if value
    ]
    if untracked_paths:
        _git(worktree, "add", "-N", "--", *untracked_paths)
    if not changed_paths:
        return b""
    return _git(worktree, "diff", "--binary", "--no-ext-diff", "HEAD").stdout


def _parse_result_document(
    document: Any,
    task_id: str,
    mode: str,
    execution_root: Path,
) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise AgentOrchestrationError("provider result must be a JSON object")
    with tempfile.TemporaryDirectory(prefix="the-pass-agent-result-") as temporary:
        path = Path(temporary) / "agent_result.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        validation = validate_artifact(path, artifact_type="agent_result")
    if not validation.ok:
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in validation.issues)
        raise AgentOrchestrationError(f"provider result is invalid: {details}")
    if document["task_id"] != task_id:
        raise AgentOrchestrationError("provider result task_id does not match task")
    for finding in document["findings"]:
        for value in finding["evidence_paths"]:
            relative = _relative_path(value, label="finding evidence_path")
            if not _inside(execution_root, relative).exists():
                raise AgentOrchestrationError(
                    f"finding evidence path does not exist: {relative}"
                )
    for value in document["changed_paths"]:
        _relative_path(value, label="result changed_path")
    if mode == "read_only" and document["changed_paths"]:
        raise AgentSafetyError("read-only provider result claims changed paths")
    return document


def _parse_provider_result(
    provider: str,
    outcome: ProcessOutcome,
    result_path: Path,
    *,
    task_id: str,
    mode: str,
    execution_root: Path,
    max_output_bytes: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    metadata: dict[str, Any] = {"session_id": None, "cost_usd": None}
    if provider == "codex":
        if not result_path.is_file():
            raise AgentOrchestrationError("codex did not write the structured result file")
        if result_path.stat().st_size > max_output_bytes:
            raise AgentOrchestrationError("codex structured result exceeded max_output_bytes")
        document = json.loads(result_path.read_text(encoding="utf-8"))
        for raw_line in outcome.stdout.decode("utf-8", errors="replace").splitlines():
            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if isinstance(event, dict) and event.get("type") == "thread.started":
                metadata["session_id"] = event.get("thread_id")
    else:
        payload = json.loads(outcome.stdout.decode("utf-8"))
        if not isinstance(payload, dict):
            raise AgentOrchestrationError("claude output must be a JSON object")
        document = payload.get("structured_output")
        if document is None and isinstance(payload.get("result"), str):
            result_text = payload["result"].strip()
            try:
                document = json.loads(result_text)
            except json.JSONDecodeError:
                fences = list(
                    re.finditer(
                        r"```(?:json)?\s*(.*?)\s*```",
                        result_text,
                        flags=re.IGNORECASE | re.DOTALL,
                    )
                )
                if len(fences) != 1:
                    raise AgentOrchestrationError(
                        "claude result string does not contain one unambiguous JSON document"
                    )
                outside = result_text[: fences[0].start()] + result_text[fences[0].end() :]
                if "```" in outside or "{" in outside or "}" in outside:
                    raise AgentOrchestrationError(
                        "claude result string contains ambiguous content outside the JSON fence"
                    )
                document = json.loads(fences[0].group(1))
        metadata["session_id"] = payload.get("session_id")
        cost = payload.get("total_cost_usd")
        metadata["cost_usd"] = float(cost) if isinstance(cost, (int, float)) else None
    return _parse_result_document(document, task_id, mode, execution_root), metadata


def _provider_output_metadata(provider: str, outcome: ProcessOutcome) -> dict[str, Any]:
    metadata: dict[str, Any] = {"session_id": None, "cost_usd": None}
    if provider == "claude":
        try:
            payload = json.loads(outcome.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return metadata
        if isinstance(payload, dict):
            metadata["session_id"] = payload.get("session_id")
            cost = payload.get("total_cost_usd")
            metadata["cost_usd"] = float(cost) if isinstance(cost, (int, float)) else None
        return metadata
    for raw_line in outcome.stdout.decode("utf-8", errors="replace").splitlines():
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict) and event.get("type") == "thread.started":
            metadata["session_id"] = event.get("thread_id")
    return metadata


def _provider_failure_details(
    provider: str, outcome: ProcessOutcome
) -> tuple[str, dict[str, Any]]:
    metadata = _provider_output_metadata(provider, outcome)
    fields: list[str] = []
    if provider == "claude":
        try:
            payload = json.loads(outcome.stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict):
            for name in ("subtype", "api_error_status", "stop_reason", "terminal_reason"):
                value = payload.get(name)
                if isinstance(value, (str, int, float, bool)):
                    fields.append(f"{name}={str(value)[:120]}")
    else:
        event_types: set[str] = set()
        for raw_line in outcome.stdout.decode("utf-8", errors="replace").splitlines():
            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            event_type = event.get("type")
            if isinstance(event_type, str):
                event_types.add(event_type[:120])
        if event_types:
            fields.append("events=" + ",".join(sorted(event_types)))
    suffix = f" ({'; '.join(fields)})" if fields else ""
    return f"provider exited with code {outcome.returncode}{suffix}", metadata


def _provider_version(prefix: Sequence[str], provider: str, policy: Mapping[str, Any]) -> str:
    try:
        result = subprocess.run(
            [*prefix, *policy["providers"][provider]["version_args"]],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"unavailable: {type(exc).__name__}"
    value = (result.stdout or result.stderr).strip().splitlines()
    return value[0][:300] if value else f"exit {result.returncode}"


def doctor_agents(provider: str = "all") -> dict[str, Any]:
    """Inspect local provider binaries without contacting model endpoints."""

    policy = load_agent_policy()
    selected = list(policy["providers"]) if provider == "all" else [provider]
    if any(value not in policy["providers"] for value in selected):
        raise AgentOrchestrationError(f"unknown provider: {provider}")
    providers = {}
    for name in selected:
        binary_name = policy["providers"][name]["binary"]
        binary = shutil.which(binary_name)
        providers[name] = {
            "available": binary is not None,
            "binary": binary,
            "version": (
                _provider_version([binary], name, policy) if binary is not None else None
            ),
            "authentication_checked": False,
            "network_contacted": False,
        }
    return {"status": "complete", "providers": providers}


def inspect_agent_task(
    task_path: Path,
    *,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """Validate a task and return a non-executing invocation preview."""

    context = validate_agent_task_file(task_path, environment=environment)
    placeholder = Path("<agent-result.json>")
    provider = context.task["target_provider"]
    argv = build_provider_argv(
        context,
        execution_root=context.workspace_root,
        result_path=placeholder,
        provider_commands={provider: [context.policy["providers"][provider]["binary"]]},
    )
    return {
        "status": "complete",
        "task_id": context.task["task_id"],
        "target_provider": provider,
        "runtime_depth": context.runtime_depth,
        "would_execute": False,
        "sanitized_argv": _sanitize_argv(argv),
        "cwd_strategy": (
            "source_read_only" if context.task["mode"] == "read_only" else "detached_worktree"
        ),
    }


def _write_create_only(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise


def _write_run(path: Path, document: dict[str, Any]) -> None:
    content = (json.dumps(document, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _write_create_only(path, content)
    validation = validate_artifact(path, artifact_type="agent_run")
    if not validation.ok:
        path.unlink(missing_ok=True)
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in validation.issues)
        raise AgentOrchestrationError(f"generated agent run is invalid: {details}")


def dispatch_agent_task(
    task_path: Path,
    *,
    output_dir: Path,
    execute: bool,
    environment: Mapping[str, str] | None = None,
    provider_commands: Mapping[str, Sequence[str]] | None = None,
) -> tuple[dict[str, Any], Path, int]:
    """Execute exactly one external provider task and create a write-once receipt."""

    if not execute:
        raise AgentSafetyError("external agent dispatch requires explicit --execute")
    context = validate_agent_task_file(task_path, environment=environment)
    max_depth = int(context.policy["limits"]["max_cross_provider_depth"])
    if context.runtime_depth >= max_depth:
        raise AgentSafetyError("cross-provider delegation depth is exhausted")
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = "agent_" + uuid.uuid4().hex
    run_path = output_dir / f"agent-run-{run_id}.json"
    result_temp = output_dir / f".{run_id}.provider-result.json"
    patch_path = output_dir / f"agent-patch-{run_id}.patch"
    provider = context.task["target_provider"]
    prefix = _provider_prefix(provider, context.policy, provider_commands)
    provider_version = _provider_version(prefix, provider, context.policy)
    started_at = _utc_now()
    result: dict[str, Any] | None = None
    metadata: dict[str, Any] = {"session_id": None, "cost_usd": None}
    patch: dict[str, Any] | None = None
    issues: list[str] = []
    status = "failed"
    exit_code = 1
    outcome = ProcessOutcome(
        returncode=None,
        stdout=b"",
        stderr=b"",
        stdout_sha256=_sha256_bytes(b""),
        stderr_sha256=_sha256_bytes(b""),
        output_exceeded=False,
        timed_out=False,
        duration_ms=0,
    )
    argv: list[str] = []
    cwd_strategy = "source_read_only"
    try:
        with _execution_workspace(context, run_id) as (execution_root, cwd_strategy):
            argv = build_provider_argv(
                context,
                execution_root=execution_root,
                result_path=result_temp,
                provider_commands=provider_commands,
            )
            outcome = _run_bounded_process(
                argv,
                prompt=_build_prompt(context),
                cwd=execution_root,
                environment=_child_environment(context, run_id),
                timeout_seconds=int(context.task["timeout_seconds"]),
                max_output_bytes=int(context.task["max_output_bytes"]),
            )
            if outcome.timed_out:
                raise AgentOrchestrationError("provider timed out")
            if outcome.output_exceeded:
                raise AgentOrchestrationError("provider output exceeded max_output_bytes")
            if outcome.returncode != 0:
                message, metadata = _provider_failure_details(provider, outcome)
                raise AgentOrchestrationError(message)
            metadata = _provider_output_metadata(provider, outcome)
            result, parsed_metadata = _parse_provider_result(
                provider,
                outcome,
                result_temp,
                task_id=context.task["task_id"],
                mode=context.task["mode"],
                execution_root=execution_root,
                max_output_bytes=int(context.task["max_output_bytes"]),
            )
            metadata.update(
                {key: value for key, value in parsed_metadata.items() if value is not None}
            )
            if context.task["mode"] == "worktree_patch":
                changed_paths = _changed_paths(execution_root)
                _validate_changed_paths(context, changed_paths)
                patch_bytes = _build_patch(execution_root, changed_paths)
                result = {**result, "changed_paths": changed_paths}
                if len(patch_bytes) > int(context.task["max_output_bytes"]):
                    raise AgentOrchestrationError(
                        "agent patch exceeded max_output_bytes"
                    )
                if patch_bytes:
                    _write_create_only(patch_path, patch_bytes)
                    patch = {
                        "path": str(patch_path),
                        "sha256": _sha256_bytes(patch_bytes),
                        "changed_paths": changed_paths,
                        "applied": False,
                    }
            if result["status"] == "complete":
                status, exit_code = "complete", 0
            elif result["status"] == "blocked":
                status, exit_code = "blocked", 2
            else:
                status, exit_code = "failed", 1
    except AgentSafetyError as exc:
        status, exit_code = "forbidden", 3
        issues.append(str(exc))
    except (AgentOrchestrationError, json.JSONDecodeError, OSError) as exc:
        issues.append(str(exc))
    finally:
        try:
            result_temp.unlink()
        except FileNotFoundError:
            pass

    finished_at = _utc_now()
    run = {
        "schema_version": 1,
        "run_id": run_id,
        "task_id": context.task["task_id"],
        "task_fingerprint": _fingerprint(context.task),
        "caller_provider": context.task["caller_provider"],
        "target_provider": provider,
        "provider": {"binary": prefix[0], "version": provider_version},
        "policy": {
            "schema_version": int(context.policy["schema_version"]),
            "interface_version": str(context.policy["interface_version"]),
            "sha256": _fingerprint(context.policy),
        },
        "role": context.task["role"],
        "mode": context.task["mode"],
        "runtime_depth": context.runtime_depth,
        "limits": {
            "timeout_seconds": int(context.task["timeout_seconds"]),
            "max_output_bytes": int(context.task["max_output_bytes"]),
            "max_budget_usd": float(context.task["max_budget_usd"]),
            "attempts": 1,
        },
        "execution": {
            "cwd_strategy": cwd_strategy,
            "sanitized_argv": _sanitize_argv(argv or prefix),
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_ms": outcome.duration_ms,
            "exit_code": outcome.returncode,
        },
        "streams": {
            "stdout_sha256": outcome.stdout_sha256,
            "stderr_sha256": outcome.stderr_sha256,
            "stdout_truncated": outcome.output_exceeded,
            "stderr_truncated": outcome.output_exceeded,
        },
        "result": result,
        "result_fingerprint": _fingerprint(result) if result is not None else None,
        "patch": patch,
        "status": status,
        "issues": issues,
        "metadata": metadata,
    }
    _write_run(run_path, run)
    return run, run_path, exit_code


def critical_paths_are_protected(policy: Mapping[str, Any] | None = None) -> bool:
    """Return whether every declared critical authority is protected from agent patches."""

    active = dict(policy or load_agent_policy())
    protected = [str(value) for value in active["protected_paths"]]
    return all(
        any(_path_matches(str(path), prefix) for prefix in protected)
        for path in active["critical_authority_paths"]
    )

"""Bounded liveness supervision for a trusted local workflow stage driver."""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import yaml

from ._infra import (
    exclusive_workflow_lock,
    json_fingerprint,
    terminate_process_strict,
    terminate_remaining_process_group,
    utc_now_iso_precise,
    write_json_atomic,
)
from .agent_orchestration import route_workflow_stage
from .attestation import (
    ATTESTATION_KEY_ENV,
    SIGNING_KEY_ENV,
)
from .gates import (
    DEFAULT_POLICY_PATH,
    GateEvaluationError,
    evaluate_gate,
    gate_attestation_artifact,
    write_gate_decision,
)
from .ledger import (
    LedgerError,
    append_gate_decision,
    read_ledger_entries,
)
from .orchestration import (
    WorkflowError,
    advance_workflow_state,
    load_pipeline_policy,
    read_workflow_state,
    verify_workflow_evidence,
    workflow_target_passes,
    write_workflow_state_atomic,
)
from .validator import parse_timestamp


class WorkflowSupervisorError(WorkflowError):
    """Raised when a supervised driver fails to make valid bounded progress."""


IMMUTABLE_STATE_FIELDS = (
    "schema_version",
    "run_id",
    "strategy_id",
    "objective",
    "target_gate",
    "strategy_owner",
    "run_owner",
    "started_at",
    "ledger_path",
)
STOP_STATUSES = {"complete", "waiting", "blocked", "killed"}
REVIEW_GATE_TRANSITIONS = {
    "review_research": "research_gate",
    "review_paper": "paper_gate",
    "review_risk": "risk_review",
}


@dataclass(frozen=True)
class _FileState:
    kind: str
    sha256: str
    mode: int


WORKSPACE_COPY_EXCLUDED_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "venv",
}


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, check=False, shell=False
    )
    if check and result.returncode != 0:
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise WorkflowSupervisorError(f"git {' '.join(args)} failed: {message}")
    return result


def _tree_snapshot(root: Path, *, excluded: set[str]) -> dict[str, _FileState]:
    snapshot: dict[str, _FileState] = {}
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if (
            any(part in WORKSPACE_COPY_EXCLUDED_NAMES for part in Path(relative).parts)
            or relative in excluded
        ):
            continue
        if path.is_symlink():
            target = os.readlink(path).encode("utf-8")
            snapshot[relative] = _FileState(
                "symlink", hashlib.sha256(target).hexdigest(), 0
            )
        elif path.is_file():
            snapshot[relative] = _FileState(
                "file", _sha256_file(path), path.stat().st_mode & 0o777
            )
    return snapshot


def _copy_workspace(source: Path, destination: Path) -> None:
    for path in source.rglob("*"):
        relative = path.relative_to(source)
        if any(part in WORKSPACE_COPY_EXCLUDED_NAMES for part in relative.parts):
            continue
        if path.is_symlink():
            raise WorkflowSupervisorError(
                f"auto workflow source cannot contain symlinks: {relative.as_posix()}"
            )

    def ignore(directory: str, names: list[str]) -> set[str]:
        del directory
        return {name for name in names if name in WORKSPACE_COPY_EXCLUDED_NAMES}

    for child in tuple(destination.iterdir()):
        if child.name == ".git":
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()
    for child in source.iterdir():
        if child.name in WORKSPACE_COPY_EXCLUDED_NAMES:
            continue
        target = destination / child.name
        if child.is_dir():
            shutil.copytree(child, target, symlinks=True, ignore=ignore)
        else:
            shutil.copy2(child, target)
    for path in destination.rglob("*"):
        relative = path.relative_to(destination)
        if any(part in WORKSPACE_COPY_EXCLUDED_NAMES for part in relative.parts):
            continue
        if path.is_symlink():
            raise WorkflowSupervisorError(
                f"auto workflow snapshot cannot contain symlinks: {relative.as_posix()}"
            )


def _remap_rooted_paths(value: Any, source: Path, destination: Path) -> Any:
    if isinstance(value, dict):
        return {
            key: _remap_rooted_paths(item, source, destination)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_remap_rooted_paths(item, source, destination) for item in value]
    if not isinstance(value, str):
        return value
    candidate = Path(value)
    if not candidate.is_absolute():
        return value
    try:
        relative = candidate.resolve(strict=False).relative_to(source)
    except ValueError:
        return value
    return str(destination / relative)


def _state_workspace_paths(state: Mapping[str, Any]) -> list[Path]:
    values: list[str] = []
    if isinstance(state.get("package_path"), str):
        values.append(str(state["package_path"]))
    values.extend(
        str(value) for value in state.get("evidence_paths", []) if isinstance(value, str)
    )
    return [Path(value).resolve(strict=False) for value in values]


class _IsolatedWorkflowTransaction:
    def __init__(
        self,
        *,
        caller_root: Path,
        worktree: Path,
        temporary_root: Path,
        proposal_path: Path,
        isolated_before: dict[str, Any],
        baseline: dict[str, _FileState],
        protected_paths: set[str],
    ) -> None:
        self.caller_root = caller_root
        self.worktree = worktree
        self.temporary_root = temporary_root
        self.proposal_path = proposal_path
        self.isolated_before = isolated_before
        self.baseline = baseline
        self.protected_paths = protected_paths
        self.changed_paths: list[str] = []
        self.patch_sha256: str | None = None
        self._backups: dict[str, tuple[bytes, int] | None] = {}
        self._applied = False

    @classmethod
    def create(
        cls,
        *,
        caller_root: Path,
        state_path: Path,
        report_path: Path,
        state: Mapping[str, Any],
    ) -> "_IsolatedWorkflowTransaction":
        top = _git(caller_root, "rev-parse", "--show-toplevel").stdout
        git_root = Path(top.decode("utf-8").strip()).resolve()
        if git_root != caller_root:
            raise WorkflowSupervisorError(
                "auto workflow cwd must be the Git repository root"
            )
        for path in _state_workspace_paths(state):
            try:
                path.relative_to(caller_root)
            except ValueError as exc:
                raise WorkflowSupervisorError(
                    "auto workflow state paths must stay inside the repository root"
                ) from exc
        temporary = Path(tempfile.mkdtemp(prefix="the-pass-workflow-worktree-"))
        worktree = temporary / "workspace"
        try:
            _git(git_root, "worktree", "add", "--detach", str(worktree), "HEAD")
            worktree = worktree.resolve()
            caller_snapshot = _tree_snapshot(caller_root, excluded=set())
            _copy_workspace(caller_root, worktree)
            if _tree_snapshot(caller_root, excluded=set()) != caller_snapshot:
                raise WorkflowSupervisorError(
                    "caller workspace changed while creating the agent snapshot"
                )
            proposal = worktree / ".the-pass-workflow-proposal.yaml"
            if proposal.exists():
                raise WorkflowSupervisorError("reserved workflow proposal path already exists")
            isolated_before = _remap_rooted_paths(dict(state), caller_root, worktree)
            write_workflow_state_atomic(proposal, isolated_before)
            excluded = {proposal.relative_to(worktree).as_posix()}
            baseline = _tree_snapshot(worktree, excluded=excluded)
            protected: set[str] = set()
            for path in (
                state_path,
                report_path,
                state_path.with_name(f"{state_path.name}.lock"),
                Path(str(state["ledger_path"])),
            ):
                try:
                    protected.add(path.resolve(strict=False).relative_to(caller_root).as_posix())
                except ValueError:
                    pass
            return cls(
                caller_root=caller_root,
                worktree=worktree,
                temporary_root=temporary,
                proposal_path=proposal,
                isolated_before=isolated_before,
                baseline=baseline,
                protected_paths=protected,
            )
        except Exception:
            _git(git_root, "worktree", "remove", "--force", str(worktree), check=False)
            _git(git_root, "worktree", "prune", check=False)
            shutil.rmtree(temporary, ignore_errors=True)
            raise

    def remap_candidate(self, candidate: Mapping[str, Any]) -> dict[str, Any]:
        return _remap_rooted_paths(dict(candidate), self.worktree, self.caller_root)

    def prepare(self, isolated_candidate: Mapping[str, Any]) -> None:
        excluded = {self.proposal_path.relative_to(self.worktree).as_posix()}
        observed = _tree_snapshot(self.worktree, excluded=excluded)
        changed = sorted(
            path
            for path in set(self.baseline) | set(observed)
            if self.baseline.get(path) != observed.get(path)
        )
        evidence_scope: set[str] = set()
        for value in isolated_candidate.get("evidence_paths", []):
            if isinstance(value, str):
                try:
                    evidence_scope.add(
                        Path(value).resolve(strict=False).relative_to(self.worktree).as_posix()
                    )
                except ValueError:
                    pass
        package_scope: str | None = None
        package_value = isolated_candidate.get("package_path")
        if isinstance(package_value, str):
            try:
                package_scope = (
                    Path(package_value)
                    .resolve(strict=False)
                    .relative_to(self.worktree)
                    .as_posix()
                )
            except ValueError:
                package_scope = None
        for relative in changed:
            name = Path(relative).name
            if relative in self.protected_paths:
                raise WorkflowSupervisorError(
                    f"auto workflow changed protected path: {relative}"
                )
            if name.startswith("gate_decision.") or name.startswith(
                "reviewer_attestation."
            ):
                raise WorkflowSupervisorError(
                    f"auto workflow changed parent-owned evidence: {relative}"
                )
            in_package = package_scope is not None and (
                relative == package_scope or relative.startswith(package_scope + "/")
            )
            stage = str(self.isolated_before.get("stage", ""))
            if in_package and stage in REVIEW_GATE_TRANSITIONS:
                allowed_prefixes = (
                    ("findings.",)
                    if stage == "review_research"
                    else (f"audit_report.{REVIEW_GATE_TRANSITIONS[stage]}.",)
                )
                if not name.startswith(allowed_prefixes):
                    raise WorkflowSupervisorError(
                        f"review stage cannot modify scientific package artifact: {relative}"
                    )
            if relative not in evidence_scope and not in_package:
                raise WorkflowSupervisorError(
                    f"auto workflow changed path outside declared evidence scope: {relative}"
                )
            state = observed.get(relative)
            if state is not None and state.kind != "file":
                raise WorkflowSupervisorError(
                    f"auto workflow produced unsupported filesystem object: {relative}"
                )
        self.changed_paths = changed
        self.patch_sha256 = _fingerprint(
            {
                "changed_paths": changed,
                "before": {
                    path: vars(self.baseline.get(path)) if self.baseline.get(path) else None
                    for path in changed
                },
                "after": {
                    path: vars(observed.get(path)) if observed.get(path) else None
                    for path in changed
                },
            }
        )

    def apply(self) -> None:
        current = _tree_snapshot(self.caller_root, excluded=set())
        for relative in self.changed_paths:
            if current.get(relative) != self.baseline.get(relative):
                raise WorkflowSupervisorError(
                    f"caller workspace changed during agent execution: {relative}"
                )
        try:
            for relative in self.changed_paths:
                source = self.worktree / relative
                target = self.caller_root / relative
                if target.is_symlink():
                    raise WorkflowSupervisorError(
                        f"caller target is a symlink: {relative}"
                    )
                if target.is_file():
                    self._backups[relative] = (
                        target.read_bytes(),
                        target.stat().st_mode & 0o777,
                    )
                else:
                    self._backups[relative] = None
                if source.is_file() and not source.is_symlink():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    descriptor, name = tempfile.mkstemp(
                        prefix=f".{target.name}.", suffix=".workflow", dir=str(target.parent)
                    )
                    try:
                        with os.fdopen(descriptor, "wb") as handle:
                            handle.write(source.read_bytes())
                            handle.flush()
                            os.fsync(handle.fileno())
                        os.chmod(name, source.stat().st_mode & 0o777)
                        os.replace(name, target)
                    finally:
                        try:
                            os.unlink(name)
                        except FileNotFoundError:
                            pass
                elif source.exists() or source.is_symlink():
                    raise WorkflowSupervisorError(
                        f"auto workflow output is not a regular file: {relative}"
                    )
                else:
                    target.unlink(missing_ok=True)
            self._applied = True
        except Exception:
            self.rollback()
            raise

    def rollback(self) -> None:
        if not self._backups:
            return
        for relative, backup in reversed(tuple(self._backups.items())):
            target = self.caller_root / relative
            if backup is None:
                target.unlink(missing_ok=True)
                continue
            payload, mode = backup
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            os.chmod(target, mode)
        self._backups.clear()
        self._applied = False

    def commit(self) -> None:
        self._backups.clear()
        self._applied = False

    def cleanup(self) -> None:
        if self._applied:
            self.rollback()
        _git(
            self.caller_root,
            "worktree",
            "remove",
            "--force",
            str(self.worktree),
            check=False,
        )
        _git(self.caller_root, "worktree", "prune", check=False)
        shutil.rmtree(self.temporary_root, ignore_errors=True)


_utc_now = utc_now_iso_precise


_fingerprint = json_fingerprint


_write_json_atomic = write_json_atomic


@contextmanager
def _exclusive_workflow_lock(state_path: Path) -> Iterator[None]:
    with exclusive_workflow_lock(state_path, WorkflowSupervisorError):
        yield


def _new_proposal_path(state_path: Path) -> Path:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{state_path.name}.proposal-",
        suffix=".yaml",
        dir=str(state_path.parent),
    )
    os.close(descriptor)
    os.unlink(name)
    return Path(name)


def validate_supervised_transition(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    policy: Mapping[str, Any] | None = None,
) -> None:
    """Reject direct rewrites that did not follow one legal workflow transition."""

    active = dict(policy or load_pipeline_policy())
    for field in IMMUTABLE_STATE_FIELDS:
        if before[field] != after[field]:
            raise WorkflowSupervisorError(
                f"supervised driver changed immutable workflow field: {field}"
            )
    current = str(before["stage"])
    destination = str(after["stage"])
    if destination != current and destination not in active["stages"][current]["transitions"]:
        raise WorkflowSupervisorError(
            f"supervised driver made an illegal stage transition: {current} -> {destination}"
        )
    transition_delta = int(after["transitions_used"]) - int(before["transitions_used"])
    expected_delta = 0 if destination == "complete" else 1
    budget_stop = (
        destination == current
        and after["status"] == "blocked"
        and transition_delta == 0
        and any("budget exhausted" in value for value in after["blockers"])
    )
    if transition_delta != expected_delta and not budget_stop:
        raise WorkflowSupervisorError(
            "supervised driver must consume exactly one transition per invocation"
        )
    remediation_delta = int(after["remediation_laps"]) - int(before["remediation_laps"])
    no_progress_delta = int(after["no_progress_laps"]) - int(before["no_progress_laps"])
    if remediation_delta not in {0, 1} or no_progress_delta not in {-1, 0, 1}:
        raise WorkflowSupervisorError("supervised driver made an invalid remediation counter jump")
    before_updated = parse_timestamp(before["updated_at"])
    after_updated = parse_timestamp(after["updated_at"])
    if before_updated is None or after_updated is None or after_updated < before_updated:
        raise WorkflowSupervisorError("supervised driver moved updated_at backwards")
    verify_workflow_evidence(dict(after))


_terminate = terminate_process_strict


_terminate_remaining_process_group = terminate_remaining_process_group


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_driver(
    argv: Sequence[str],
    *,
    cwd: Path,
    environment: Mapping[str, str],
    timeout_seconds: int,
    max_output_bytes: int,
    stdin_text: str | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="the-pass-supervisor-io-") as temporary:
        root = Path(temporary)
        stdin_path = root / "stdin.txt"
        stdout_path = root / "stdout.bin"
        stderr_path = root / "stderr.bin"
        stdin_path.write_text(stdin_text or "", encoding="utf-8")
        with (
            stdin_path.open("rb") as stdin,
            stdout_path.open("wb") as stdout,
            stderr_path.open("wb") as stderr,
        ):
            process = subprocess.Popen(
                list(argv),
                cwd=cwd,
                env=dict(environment),
                stdout=stdout,
                stderr=stderr,
                stdin=stdin if stdin_text is not None else subprocess.DEVNULL,
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
            _terminate_remaining_process_group(process)
        output_exceeded = output_exceeded or (
            stdout_path.stat().st_size + stderr_path.stat().st_size > max_output_bytes
        )
        return {
            "exit_code": returncode,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "timed_out": timed_out,
            "output_exceeded": output_exceeded,
            "stdout_sha256": _sha256_file(stdout_path),
            "stderr_sha256": _sha256_file(stderr_path),
        }


def _auto_driver_argv(route: Mapping[str, Any], cwd: Path) -> list[str]:
    provider = route["provider"]
    if provider not in {"codex", "claude"}:
        raise WorkflowSupervisorError("auto driver requires an agent-routed stage")
    binary = shutil.which(provider)
    if binary is None:
        raise WorkflowSupervisorError(f"auto driver provider is not installed: {provider}")
    model = str(route["requested_model"])
    effort = route["reasoning_effort"]
    if provider == "codex":
        return [
            binary,
            "exec",
            "--ephemeral",
            "--model",
            model,
            "--config",
            f'model_reasoning_effort="{effort}"',
            "--json",
            "--color",
            "never",
            "--sandbox",
            "workspace-write",
            "--disable",
            "apps",
            "--disable",
            "browser_use",
            "--disable",
            "computer_use",
            "--disable",
            "hooks",
            "--disable",
            "image_generation",
            "--disable",
            "multi_agent",
            "--disable",
            "plugins",
            "--config",
            "mcp_servers={}",
            "--config",
            "hooks={}",
            "--config",
            "plugins={}",
            "--cd",
            str(cwd.resolve()),
            "-",
        ]
    argv = [
        binary,
        "-p",
        "--output-format",
        "json",
        "--no-session-persistence",
        "--model",
        model,
        "--permission-mode",
        "acceptEdits",
        "--setting-sources",
        "",
        "--strict-mcp-config",
        "--mcp-config",
        '{"mcpServers":{}}',
        "--no-chrome",
        "--disable-slash-commands",
        "--tools",
        "Read,Glob,Grep,Edit,Write,Bash",
        "--disallowedTools",
        "Agent",
    ]
    if effort is not None:
        argv.extend(["--effort", str(effort)])
    return argv


def _auto_driver_prompt(state: Mapping[str, Any], route: Mapping[str, Any]) -> str:
    return f"""You are one bounded The Pass workflow stage driver.

Repository: current working directory
State: {state['run_id']} at {state['stage']} targeting {state['target_gate']}
State file: $THE_PASS_WORKFLOW_STATE
Assigned role: {route['role']}

Execute exactly the current stage, following the installed The Pass skill contract and repository
instructions. Inspect the state first. Produce and validate all evidence required by this stage,
then invoke `the-pass workflow advance` exactly once so the durable state changes. Do not perform a
second stage. Do not claim completion in prose; the supervisor trusts only validated state.

Do not place or prepare live orders, access venue credentials, alter a recorded package, edit gate
decisions or ledgers directly, bypass reviewer independence, or delegate to another provider. Stop
with a valid blocked, waiting, or killed checkpoint when required evidence cannot be produced.
"""


def _decision_is_recorded(
    ledger_path: Path, package_id: str, gate: str
) -> bool:
    if not ledger_path.exists():
        return False
    return any(
        entry.get("entry_kind") == "gate_decision"
        and entry.get("package_id") == package_id
        and entry.get("gate") == gate
        for entry in read_ledger_entries(ledger_path)
    )


def _run_deterministic_stage(state_path: Path, state: Mapping[str, Any]) -> None:
    stage = str(state["stage"])
    if stage == "preflight":
        updated = advance_workflow_state(
            dict(state),
            to_stage="research",
            status="in_progress",
            next_action="execute research stage",
        )
        write_workflow_state_atomic(state_path, updated)
        return
    if stage in REVIEW_GATE_TRANSITIONS:
        gate = REVIEW_GATE_TRANSITIONS[stage]
        package_value = state.get("package_path")
        package_id = state.get("package_id")
        reviewer = state.get("reviewer")
        if not all(
            isinstance(value, str) and value
            for value in (package_value, package_id, reviewer)
        ):
            raise WorkflowSupervisorError(
                f"deterministic review stage {stage} requires package and reviewer state"
            )
        public_evidence, _, blockers = gate_attestation_artifact(
            Path(str(package_value)),
            gate,
            str(reviewer),
            str(package_id),
            None,
        )
        if blockers:
            raise WorkflowSupervisorError(
                f"reviewer attestation is not ready: {'; '.join(blockers)}"
            )
        updated = advance_workflow_state(
            dict(state),
            to_stage=gate,
            status="in_progress",
            next_action=f"evaluate {gate}",
            reviewer=str(reviewer),
            evidence_paths=[*state["evidence_paths"], *public_evidence],
        )
        write_workflow_state_atomic(state_path, updated)
        return
    if stage not in {"research_gate", "paper_gate", "risk_review"}:
        raise WorkflowSupervisorError(
            f"deterministic auto driver cannot execute workflow stage {stage}"
        )
    package_value = state.get("package_path")
    package_id = state.get("package_id")
    reviewer = state.get("reviewer")
    if not all(isinstance(value, str) and value for value in (package_value, package_id, reviewer)):
        raise WorkflowSupervisorError(
            f"deterministic gate stage {stage} requires package and reviewer state"
        )
    package = Path(str(package_value)).resolve()
    ledger = Path(str(state["ledger_path"])).resolve()
    decision_path = package / f"gate_decision.{stage}.yaml"
    if not decision_path.exists():
        evaluation = evaluate_gate(
            package,
            gate=stage,
            reviewer=str(reviewer),
            policy_path=DEFAULT_POLICY_PATH,
            ledger_path=ledger,
        )
        write_gate_decision(decision_path, evaluation.decision)
        gate_result = str(evaluation.decision["gate_result"])
    else:
        decision = yaml.safe_load(decision_path.read_text(encoding="utf-8"))
        if not isinstance(decision, dict):
            raise WorkflowSupervisorError("existing gate decision must be an object")
        gate_result = str(decision.get("gate_result"))
    if not _decision_is_recorded(ledger, str(package_id), stage):
        append_gate_decision(ledger, decision_path)
    if gate_result == "pass" and workflow_target_passes(dict(state)):
        destination, status, next_action, blockers = (
            "complete",
            "complete",
            f"target {stage} passed",
            [],
        )
    elif gate_result == "pass":
        destination = {"research_gate": "paper_prepare", "paper_gate": "risk_prepare"}[stage]
        status, next_action, blockers = "in_progress", f"execute {destination}", []
    else:
        destination = stage
        status = "killed" if gate_result == "kill" else "blocked"
        next_action = "resolve gate blockers in a superseding package"
        blockers = [f"{stage} result is {gate_result}"]
    updated = advance_workflow_state(
        dict(state),
        to_stage=destination,
        status=status,
        next_action=next_action,
        blockers=blockers,
    )
    write_workflow_state_atomic(state_path, updated)


def inspect_workflow_execution(
    state_path: Path,
    *,
    driver_argv: Sequence[str],
    author_provider: str | None,
    available_providers: Sequence[str],
) -> dict[str, Any]:
    state = read_workflow_state(state_path)
    route = route_workflow_stage(
        state["stage"],
        author_provider=author_provider,
        available_providers=available_providers,
    )
    return {
        "status": state["status"],
        "would_execute": False,
        "state_path": str(state_path.resolve()),
        "driver": {
            "executable": str(driver_argv[0]) if driver_argv else None,
            "argv_sha256": _fingerprint(list(driver_argv)),
        },
        "route": route,
        "workflow": state,
    }


def _supervise_workflow_locked(
    state_path: Path,
    *,
    driver_argv: Sequence[str],
    cwd: Path,
    report_path: Path,
    author_provider: str | None = None,
    available_providers: Sequence[str] = ("codex", "claude"),
    max_cycles: int | None = None,
    timeout_seconds: int = 1800,
    max_output_bytes: int = 4_194_304,
    environment: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], int]:
    """Invoke a trusted stage driver until a valid terminal workflow checkpoint."""

    if not driver_argv or not str(driver_argv[0]).strip():
        raise WorkflowSupervisorError("workflow supervisor requires a driver command")
    if timeout_seconds <= 0 or timeout_seconds > 1800:
        raise WorkflowSupervisorError("supervisor timeout_seconds must be in 1..1800")
    if max_output_bytes < 1024 or max_output_bytes > 4_194_304:
        raise WorkflowSupervisorError(
            "supervisor max_output_bytes must be in 1024..4194304"
        )
    state_path = state_path.resolve()
    report_path = report_path.resolve()
    cwd = cwd.resolve()
    if not cwd.is_dir():
        raise WorkflowSupervisorError("supervisor cwd must be an existing directory")
    if report_path.parent != state_path.parent or report_path == state_path:
        raise WorkflowSupervisorError(
            "supervisor report must be a distinct file beside workflow state"
        )
    policy = load_pipeline_policy()
    state = read_workflow_state(state_path)
    remaining = policy["runtime"]["max_transitions"] - state["transitions_used"] + 1
    cycle_limit = remaining if max_cycles is None else min(max_cycles, remaining)
    if cycle_limit <= 0:
        raise WorkflowSupervisorError("workflow supervisor cycle budget is exhausted")
    report: dict[str, Any] = {
        "schema_version": 1,
        "run_id": state["run_id"],
        "state_path": str(state_path.resolve()),
        "started_at": _utc_now(),
        "updated_at": _utc_now(),
        "status": "running",
        "driver": {
            "executable": str(driver_argv[0]),
            "argv_sha256": _fingerprint(list(driver_argv)),
        },
        "limits": {
            "max_cycles": cycle_limit,
            "timeout_seconds": timeout_seconds,
            "max_output_bytes": max_output_bytes,
        },
        "cycles": [],
        "final_workflow_status": None,
        "issues": [],
    }
    _write_json_atomic(report_path, report)

    active_proposal: Path | None = None
    active_transaction: _IsolatedWorkflowTransaction | None = None

    def fail(message: str) -> None:
        nonlocal active_proposal, active_transaction
        if active_transaction is not None:
            active_transaction.rollback()
            active_transaction.cleanup()
            active_transaction = None
            active_proposal = None
        if active_proposal is not None:
            try:
                active_proposal.unlink()
            except FileNotFoundError:
                pass
            active_proposal = None
        report["status"] = "failed"
        report["final_workflow_status"] = state["status"]
        report["issues"] = [message]
        report["updated_at"] = _utc_now()
        _write_json_atomic(report_path, report)
        raise WorkflowSupervisorError(message)

    if state["status"] in STOP_STATUSES:
        report["status"] = state["status"]
        report["final_workflow_status"] = state["status"]
        report["updated_at"] = _utc_now()
        _write_json_atomic(report_path, report)
        return report, 0 if state["status"] == "complete" else 2

    base_environment = dict(os.environ if environment is None else environment)
    auto_driver = list(driver_argv) == ["auto"]
    routed_providers = tuple(
        provider
        for provider in available_providers
        if not auto_driver or shutil.which(provider) is not None
    )
    effective_author_provider = author_provider
    for index in range(1, cycle_limit + 1):
        before = state
        before_fingerprint = _fingerprint(before)
        try:
            route = route_workflow_stage(
                before["stage"],
                author_provider=effective_author_provider,
                available_providers=routed_providers or available_providers,
            )
            if auto_driver and route["execution"] == "agent":
                if not routed_providers:
                    fail("auto driver requires an installed Codex or Claude CLI")
                if route["provider"] not in routed_providers:
                    route = route_workflow_stage(
                        before["stage"],
                        author_provider=effective_author_provider,
                        available_providers=routed_providers,
                    )
            if (
                auto_driver
                and before["stage"] in REVIEW_GATE_TRANSITIONS
                and isinstance(before.get("package_path"), str)
                and isinstance(before.get("package_id"), str)
                and isinstance(before.get("reviewer"), str)
            ):
                _, _, attestation_blockers = gate_attestation_artifact(
                    Path(str(before["package_path"])),
                    REVIEW_GATE_TRANSITIONS[str(before["stage"])],
                    str(before["reviewer"]),
                    str(before["package_id"]),
                    None,
                )
                if not attestation_blockers:
                    route = {
                        **route,
                        "execution": "deterministic",
                        "provider": None,
                        "requested_model": None,
                        "resolved_profile": None,
                        "reasoning_effort": None,
                        "role": "supervisor",
                    }
        except (WorkflowError, ValueError) as exc:
            fail(str(exc))
        validation_before = before
        execution_cwd = cwd
        workspace_mode = "trusted_direct"
        if auto_driver and route["execution"] == "agent":
            try:
                active_transaction = _IsolatedWorkflowTransaction.create(
                    caller_root=cwd,
                    state_path=state_path,
                    report_path=report_path,
                    state=before,
                )
            except (OSError, subprocess.SubprocessError, WorkflowError) as exc:
                fail(f"isolated workflow workspace could not be created: {exc}")
            active_proposal = active_transaction.proposal_path
            validation_before = active_transaction.isolated_before
            execution_cwd = active_transaction.worktree
            workspace_mode = "detached_worktree_transaction"
        else:
            active_proposal = _new_proposal_path(state_path)
            write_workflow_state_atomic(active_proposal, before)
        child_environment = dict(base_environment)
        if auto_driver:
            allowed_names = {
                "PATH",
                "HOME",
                "USER",
                "TMPDIR",
                "LANG",
                "LC_ALL",
                "CODEX_HOME",
                "CLAUDE_CONFIG_DIR",
            }
            child_environment = {
                name: value
                for name, value in child_environment.items()
                if name in allowed_names
            }
        child_environment.update(
            {
                "THE_PASS_WORKFLOW_STATE": str(active_proposal.resolve()),
                "THE_PASS_WORKFLOW_STAGE": str(before["stage"]),
                "THE_PASS_WORKFLOW_STATUS": str(before["status"]),
                "THE_PASS_WORKFLOW_TARGET_GATE": str(before["target_gate"]),
                "THE_PASS_WORKFLOW_RUN_ID": str(before["run_id"]),
                "THE_PASS_ROUTE_PROVIDER": str(route["provider"] or "supervisor"),
                "THE_PASS_ROUTE_MODEL": str(route["requested_model"] or "none"),
                "THE_PASS_ROUTE_PROFILE": str(route["resolved_profile"] or "none"),
                "THE_PASS_ROUTE_EFFORT": str(route["reasoning_effort"] or "none"),
                "THE_PASS_ROUTE_ROLE": str(route["role"]),
                "THE_PASS_SUPERVISOR_CYCLE": str(index),
            }
        )
        child_environment.pop(ATTESTATION_KEY_ENV, None)
        child_environment.pop(SIGNING_KEY_ENV, None)
        if auto_driver and route["execution"] == "deterministic":
            started = time.monotonic()
            try:
                _run_deterministic_stage(active_proposal, before)
            except (
                GateEvaluationError,
                LedgerError,
                OSError,
                ValueError,
                WorkflowError,
            ) as exc:
                fail(str(exc))
            outcome = {
                "exit_code": 0,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "timed_out": False,
                "output_exceeded": False,
                "stdout_sha256": hashlib.sha256(b"").hexdigest(),
                "stderr_sha256": hashlib.sha256(b"").hexdigest(),
            }
        else:
            try:
                effective_argv = (
                    _auto_driver_argv(route, execution_cwd)
                    if auto_driver
                    else driver_argv
                )
                prompt = _auto_driver_prompt(before, route) if auto_driver else None
                outcome = _run_driver(
                    effective_argv,
                    cwd=execution_cwd,
                    environment=child_environment,
                    timeout_seconds=timeout_seconds,
                    max_output_bytes=max_output_bytes,
                    stdin_text=prompt,
                )
            except (OSError, subprocess.SubprocessError, WorkflowError) as exc:
                fail(f"workflow driver could not execute: {exc}")
        if outcome["timed_out"]:
            fail("workflow driver timed out")
        if outcome["output_exceeded"]:
            fail("workflow driver output exceeded max_output_bytes")
        try:
            candidate = read_workflow_state(active_proposal)
        except WorkflowError as exc:
            fail(f"workflow driver wrote invalid state: {exc}")
        pending_gate = REVIEW_GATE_TRANSITIONS.get(str(validation_before["stage"]))
        if (
            route["execution"] == "agent"
            and pending_gate is not None
            and candidate.get("stage") == pending_gate
        ):
            candidate = {
                **candidate,
                "stage": validation_before["stage"],
                "status": "waiting",
                "blockers": [
                    f"{pending_gate} requires an independently signed Ed25519 reviewer attestation"
                ],
                "next_action": (
                    f"run the-pass gate attest for {pending_gate}, then resume workflow execute"
                ),
            }
        isolated_after_fingerprint = _fingerprint(candidate)
        if isolated_after_fingerprint == _fingerprint(validation_before):
            fail("workflow driver exited without checkpoint progress")
        try:
            validate_supervised_transition(validation_before, candidate, policy=policy)
        except WorkflowError as exc:
            fail(str(exc))
        try:
            current = read_workflow_state(state_path)
        except WorkflowError as exc:
            fail(f"canonical workflow state became invalid during execution: {exc}")
        if _fingerprint(current) != before_fingerprint:
            fail("canonical workflow state changed during supervised execution")
        if active_transaction is not None:
            isolated_candidate = candidate
            candidate = active_transaction.remap_candidate(isolated_candidate)
            try:
                active_transaction.prepare(isolated_candidate)
                active_transaction.apply()
                validate_supervised_transition(before, candidate, policy=policy)
            except (OSError, WorkflowError) as exc:
                fail(f"isolated workflow patch was rejected: {exc}")
        after_fingerprint = _fingerprint(candidate)
        try:
            write_workflow_state_atomic(state_path, candidate)
        except Exception:
            if active_transaction is not None:
                active_transaction.rollback()
                active_transaction.cleanup()
                active_transaction = None
                active_proposal = None
            raise
        state = candidate
        transaction_evidence = {
            "workspace_mode": workspace_mode,
            "changed_paths": [],
            "patch_sha256": None,
        }
        if active_transaction is not None:
            transaction_evidence.update(
                {
                    "changed_paths": active_transaction.changed_paths,
                    "patch_sha256": active_transaction.patch_sha256,
                }
            )
            active_transaction.commit()
            active_transaction.cleanup()
            active_transaction = None
        elif active_proposal is not None:
            try:
                active_proposal.unlink()
            except FileNotFoundError:
                pass
        active_proposal = None
        cycle = {
            "index": index,
            "stage_before": before["stage"],
            "status_before": before["status"],
            "stage_after": state["stage"],
            "status_after": state["status"],
            "state_sha256_before": before_fingerprint,
            "state_sha256_after": after_fingerprint,
            "route": route,
            "driver": outcome,
            "workspace_transaction": transaction_evidence,
        }
        report["cycles"].append(cycle)
        if route["execution"] == "agent" and route["role"] == "implementer":
            effective_author_provider = str(route["provider"])
        report["updated_at"] = _utc_now()
        _write_json_atomic(report_path, report)
        if outcome["exit_code"] != 0 and state["status"] not in {
            "waiting",
            "blocked",
            "killed",
        }:
            fail(f"workflow driver failed with exit code {outcome['exit_code']}")
        if state["status"] in STOP_STATUSES:
            report["status"] = state["status"]
            report["final_workflow_status"] = state["status"]
            report["updated_at"] = _utc_now()
            _write_json_atomic(report_path, report)
            return report, 0 if state["status"] == "complete" else 2

    report["status"] = "failed"
    report["final_workflow_status"] = state["status"]
    report["issues"] = ["supervisor cycle budget exhausted before a terminal checkpoint"]
    report["updated_at"] = _utc_now()
    _write_json_atomic(report_path, report)
    return report, 1


def supervise_workflow(
    state_path: Path,
    *,
    driver_argv: Sequence[str],
    cwd: Path,
    report_path: Path,
    author_provider: str | None = None,
    available_providers: Sequence[str] = ("codex", "claude"),
    max_cycles: int | None = None,
    timeout_seconds: int = 1800,
    max_output_bytes: int = 4_194_304,
    environment: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], int]:
    """Run one transactional supervisor for a canonical workflow state."""

    with _exclusive_workflow_lock(state_path):
        return _supervise_workflow_locked(
            state_path,
            driver_argv=driver_argv,
            cwd=cwd,
            report_path=report_path,
            author_provider=author_provider,
            available_providers=available_providers,
            max_cycles=max_cycles,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
            environment=environment,
        )

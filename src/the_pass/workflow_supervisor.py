"""Bounded liveness supervision for a trusted local workflow stage driver."""

from __future__ import annotations

import hashlib
import json
import os
import signal
import shutil
import subprocess
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

import yaml

from .agent_orchestration import route_workflow_stage
from .attestation import (
    ATTESTATION_KEY_ENV,
    AttestationError,
    attestation_path,
    create_reviewer_attestation,
    review_task_path,
    write_reviewer_attestation,
)
from .gates import (
    DEFAULT_POLICY_PATH,
    GateEvaluationError,
    evaluate_gate,
    write_gate_decision,
)
from .ledger import (
    LedgerError,
    append_gate_decision,
    build_run_entry,
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


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _write_json_atomic(path: Path, document: Mapping[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


@contextmanager
def _exclusive_workflow_lock(state_path: Path) -> Iterator[None]:
    """Serialize supervisors for one canonical workflow state without stale lock cleanup."""

    state_path = state_path.resolve()
    lock_path = state_path.with_name(f"{state_path.name}.lock")
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_path, flags, 0o600)
    acquired = False
    try:
        metadata = os.fstat(descriptor)
        if not lock_path.is_file() or lock_path.is_symlink():
            raise WorkflowSupervisorError("workflow lock must be a regular file")
        if hasattr(os, "getuid") and metadata.st_uid != os.getuid():
            raise WorkflowSupervisorError("workflow lock has an unexpected owner")
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        if os.name == "nt":
            import msvcrt

            if metadata.st_size == 0:
                os.write(descriptor, b"0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise WorkflowSupervisorError(
                    "another supervisor is active for this workflow state"
                ) from exc
        else:
            import fcntl

            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise WorkflowSupervisorError(
                    "another supervisor is active for this workflow state"
                ) from exc
        acquired = True
        yield
    finally:
        if acquired:
            if os.name == "nt":
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


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


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name != "nt":
            os.killpg(process.pid, signal.SIGTERM)
        else:
            process.terminate()
        process.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        if os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        else:
            process.kill()
        process.wait()


def _terminate_remaining_process_group(process: subprocess.Popen[bytes]) -> None:
    if os.name == "nt":
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    time.sleep(0.05)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


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

    def fail(message: str) -> None:
        nonlocal active_proposal
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
        active_proposal = _new_proposal_path(state_path)
        write_workflow_state_atomic(active_proposal, before)
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
        except (WorkflowError, ValueError) as exc:
            fail(str(exc))
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
                    _auto_driver_argv(route, cwd) if auto_driver else driver_argv
                )
                prompt = _auto_driver_prompt(before, route) if auto_driver else None
                outcome = _run_driver(
                    effective_argv,
                    cwd=cwd,
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
        after_fingerprint = _fingerprint(candidate)
        if after_fingerprint == before_fingerprint:
            fail("workflow driver exited without checkpoint progress")
        try:
            validate_supervised_transition(before, candidate, policy=policy)
        except WorkflowError as exc:
            fail(str(exc))
        try:
            current = read_workflow_state(state_path)
        except WorkflowError as exc:
            fail(f"canonical workflow state became invalid during execution: {exc}")
        if _fingerprint(current) != before_fingerprint:
            fail("canonical workflow state changed during supervised execution")
        created_attestation: Path | None = None
        gate = REVIEW_GATE_TRANSITIONS.get(str(before["stage"]))
        if gate is not None and candidate["stage"] == gate:
            package_value = candidate.get("package_path")
            reviewer = candidate.get("reviewer")
            if not isinstance(package_value, str) or not isinstance(reviewer, str):
                fail("review transition requires package_path and reviewer")
            package = Path(package_value).resolve()
            package_id = build_run_entry(package)["package_id"]
            if candidate.get("package_id") != package_id:
                fail("review transition package_id does not match current package")
            reviewer_provider = str(route.get("provider") or "external")
            author = str(effective_author_provider or "human")
            try:
                task_path = review_task_path(package, gate)
                attestation = create_reviewer_attestation(
                    gate=gate,
                    package_id=package_id,
                    reviewer=reviewer,
                    principal_type="provider",
                    provider=reviewer_provider,
                    model=str(route.get("requested_model") or "external-driver"),
                    run_id=str(candidate["run_id"]),
                    author_provider=author,
                    reviewer_provider=reviewer_provider,
                    evidence={
                        "state_before_sha256": before_fingerprint,
                        "state_after_sha256": after_fingerprint,
                        "stdout_sha256": outcome["stdout_sha256"],
                        "stderr_sha256": outcome["stderr_sha256"],
                        "task_sha256": _sha256_file(task_path),
                    },
                    key=base_environment.get(ATTESTATION_KEY_ENV),
                )
                created_attestation = attestation_path(package, gate)
                write_reviewer_attestation(created_attestation, attestation)
            except (AttestationError, OSError, ValueError) as exc:
                fail(f"review attestation failed: {exc}")
        try:
            write_workflow_state_atomic(state_path, candidate)
        except Exception:
            if created_attestation is not None:
                created_attestation.unlink(missing_ok=True)
            raise
        state = candidate
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

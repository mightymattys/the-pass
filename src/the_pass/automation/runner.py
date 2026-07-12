"""Whitelisted scheduler-neutral automation runner."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

import yaml

from the_pass.data.contracts import stable_fingerprint
from the_pass.incident import build_incident_report
from the_pass.safety import contains_sensitive_key
from the_pass.validator import parse_timestamp, validate_artifact


AUTOMATION_COMMANDS = (
    "data_health",
    "corpus_refresh",
    "nightly_baselines",
    "gate_checker",
    "paper_observer",
    "risk_monitor",
    "drift_report",
    "tca_report",
    "weekly_research_summary",
)
RETRYABLE_COMMANDS = {
    "data_health",
    "corpus_refresh",
    "risk_monitor",
    "drift_report",
    "tca_report",
    "weekly_research_summary",
}
REQUIRED_FORBIDDEN = {"gate_decision", "live_transaction", "credential_access"}
ALERT_SINKS = {"local_incident_artifact"}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def _write_json(path: Path, document: object) -> None:
    _write_atomic(path, json.dumps(document, indent=2, sort_keys=True) + "\n")


def _worker_outputs(staging: Path) -> list[Path]:
    manifest_path = staging / "worker-result.json"
    if not manifest_path.is_file():
        raise RuntimeError("automation worker did not produce worker-result.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    values = manifest.get("outputs") if isinstance(manifest, dict) else None
    if not isinstance(values, list) or not values:
        raise RuntimeError("automation worker returned no outputs")
    outputs = []
    for value in values:
        if not isinstance(value, str) or not value:
            raise RuntimeError("automation worker output path is invalid")
        path = (staging / value).resolve()
        try:
            path.relative_to(staging)
        except ValueError as exc:
            raise RuntimeError("automation worker output escapes staging") from exc
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"automation worker output does not exist: {value}")
        outputs.append(path)
    return outputs


def _promote_outputs(staging: Path, output_dir: Path, idempotency_key: str) -> list[Path]:
    sources = _worker_outputs(staging)
    relative_paths = [source.relative_to(staging) for source in sources]
    commit_root = output_dir / "committed" / idempotency_key
    commit_root.parent.mkdir(parents=True, exist_ok=True)
    if commit_root.exists():
        raise RuntimeError("automation commit directory already exists without a run receipt")
    os.rename(staging, commit_root)
    return [commit_root / relative for relative in relative_paths]


def _log_attempt(output_dir: Path, idempotency_key: str, attempt: int, stream: str, content: str) -> Path:
    path = output_dir / f"automation-{idempotency_key}.attempt-{attempt}.{stream}.log"
    _write_atomic(path, content[-4000:] if content else "")
    return path


def _within_allowed(output_dir: Path, workspace_root: Path, allowed_writes: list[str]) -> bool:
    for relative in allowed_writes:
        allowed = (workspace_root / relative).resolve()
        try:
            output_dir.relative_to(allowed)
        except ValueError:
            continue
        return True
    return False


def run_automation_spec(
    spec_path: Path,
    *,
    output_dir: Path,
    scheduled_for: str,
    workspace_root: Path,
    worker_command: Sequence[str] | None = None,
) -> tuple[dict[str, Any], Path]:
    spec_path = spec_path.resolve()
    workspace_root = workspace_root.resolve()
    output_dir = output_dir.resolve()
    validation = validate_artifact(spec_path, artifact_type="automation_spec")
    if not validation.ok:
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in validation.issues)
        raise ValueError(f"automation spec is invalid: {details}")
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    command = spec["command"]
    if spec.get("enabled") is not True:
        raise ValueError("automation spec is disabled")
    if command not in AUTOMATION_COMMANDS:
        raise ValueError(f"automation command is not whitelisted: {command}")
    if not REQUIRED_FORBIDDEN <= set(spec["forbidden_actions"]):
        raise ValueError("automation spec must forbid gate decisions, live transactions, and credential access")
    if spec["alert_sink"] not in ALERT_SINKS:
        raise ValueError(f"automation alert sink is not supported: {spec['alert_sink']}")
    if contains_sensitive_key(spec["inputs"]):
        raise ValueError("automation inputs contain a credential-like field")
    if parse_timestamp(scheduled_for) is None:
        raise ValueError("scheduled_for must be an RFC 3339 timestamp")
    attempts_allowed = int(spec["retry_policy"]["max_attempts"])
    if attempts_allowed > 1 and command not in RETRYABLE_COMMANDS:
        raise ValueError(f"automation command is not retryable: {command}")
    if not _within_allowed(output_dir, workspace_root, spec["allowed_writes"]):
        raise ValueError("automation output escapes allowed_writes")
    output_dir.mkdir(parents=True, exist_ok=True)
    idempotency_key = stable_fingerprint(
        {
            "spec": stable_fingerprint(spec),
            "scheduled_for": scheduled_for,
            "inputs": spec["inputs"],
        }
    )
    run_path = output_dir / f"automation-{idempotency_key}.json"
    if run_path.exists():
        return json.loads(run_path.read_text(encoding="utf-8")), run_path
    errors = []
    outputs: list[Path] = []
    evidence_logs: list[Path] = []
    attempts = 0
    started_at = _utc_now_iso()
    command_prefix = list(worker_command or (sys.executable, "-m", "the_pass.automation.worker"))
    inputs_path = output_dir / f"automation-{idempotency_key}.inputs.json"
    _write_json(inputs_path, spec["inputs"])
    for attempt in range(1, attempts_allowed + 1):
        attempts = attempt
        staging = output_dir / ".staging" / f"{idempotency_key}-{attempt}"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        try:
            process = subprocess.run(
                [
                    *command_prefix,
                    "--command",
                    command,
                    "--inputs",
                    str(inputs_path),
                    "--output-dir",
                    str(staging),
                    "--attempt",
                    str(attempt),
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=int(spec["timeout_seconds"]),
                cwd=workspace_root,
            )
            if process.stdout:
                evidence_logs.append(_log_attempt(output_dir, idempotency_key, attempt, "stdout", process.stdout))
            if process.stderr:
                evidence_logs.append(_log_attempt(output_dir, idempotency_key, attempt, "stderr", process.stderr))
            if process.returncode != 0:
                raise RuntimeError(f"worker exited {process.returncode}: {process.stderr.strip()}")
            outputs = _promote_outputs(staging, output_dir, idempotency_key)
            break
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            if stdout:
                evidence_logs.append(_log_attempt(output_dir, idempotency_key, attempt, "stdout", stdout))
            if stderr:
                evidence_logs.append(_log_attempt(output_dir, idempotency_key, attempt, "stderr", stderr))
            errors.append(f"TimeoutExpired: exceeded {spec['timeout_seconds']} seconds")
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        if command not in RETRYABLE_COMMANDS:
            break
    try:
        inputs_path.unlink()
    except FileNotFoundError:
        pass

    incident_path: Path | None = None
    status = "complete" if outputs else "frozen"
    if not outputs:
        incident_path = output_dir / f"incident-{idempotency_key}.json"
        incident = build_incident_report(
            incident_id=f"automation-incident-{idempotency_key[:16]}",
            severity="P2",
            detected_at=_utc_now_iso(),
            source=command,
            summary=errors[-1] if errors else "automation produced no output",
            evidence=[
                f"automation_run:{run_path.name}",
                f"alert_sink:{spec['alert_sink']}",
                *(str(path.relative_to(workspace_root)) for path in evidence_logs),
            ],
            freeze_reason=spec["freeze_procedure"],
        )
        _write_json(incident_path, incident)
        incident_validation = validate_artifact(incident_path, artifact_type="incident_report")
        if not incident_validation.ok:
            raise RuntimeError("generated automation incident does not validate")
    document = {
        "schema_version": 2,
        "id": f"automation-run-{idempotency_key[:16]}",
        "automation_spec": str(spec_path.relative_to(workspace_root)),
        "idempotency_key": idempotency_key,
        "started_at": started_at,
        "finished_at": _utc_now_iso(),
        "attempts": attempts,
        "status": status,
        "outputs": [str(path.relative_to(workspace_root)) for path in outputs],
        "errors": errors,
        "receipt": {
            "command": command,
            "spec_fingerprint": stable_fingerprint(spec),
            "inputs_fingerprint": stable_fingerprint(spec["inputs"]),
            "forbidden_actions_enforced": True,
            "process_isolated": True,
            "timeout_seconds": spec["timeout_seconds"],
            "staged_outputs_committed": bool(outputs),
            "alert_sink": spec["alert_sink"],
            "freeze_procedure": spec["freeze_procedure"],
            "incident_report": str(incident_path.relative_to(workspace_root)) if incident_path else None,
            "evidence_logs": [str(path.relative_to(workspace_root)) for path in evidence_logs],
        },
    }
    _write_json(run_path, document)
    result = validate_artifact(run_path, artifact_type="automation_run")
    if not result.ok:
        raise RuntimeError("generated automation run does not validate")
    return document, run_path

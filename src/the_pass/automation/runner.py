"""Whitelisted scheduler-neutral automation runner."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import yaml

from the_pass.data.contracts import stable_fingerprint
from the_pass.validator import validate_artifact


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


def _default_executor(command: str, inputs: dict[str, Any], output_dir: Path) -> list[Path]:
    output = output_dir / f"{command}-snapshot.json"
    output.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "command": command,
                "inputs_fingerprint": stable_fingerprint(inputs),
                "status": "complete",
                "read_only_external_boundary": True,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return [output]


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
    executor: Callable[[str, dict[str, Any], Path], list[Path]] | None = None,
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
    attempts = 0
    runner = executor or _default_executor
    for attempt in range(1, attempts_allowed + 1):
        attempts = attempt
        try:
            outputs = runner(command, dict(spec["inputs"]), output_dir)
            break
        except Exception as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            if command not in RETRYABLE_COMMANDS:
                break
    status = "complete" if outputs else "failed"
    document = {
        "schema_version": 2,
        "id": f"automation-run-{idempotency_key[:16]}",
        "automation_spec": str(spec_path.relative_to(workspace_root)),
        "idempotency_key": idempotency_key,
        "started_at": scheduled_for,
        "finished_at": scheduled_for,
        "attempts": attempts,
        "status": status,
        "outputs": [str(path.relative_to(workspace_root)) for path in outputs],
        "errors": errors,
        "receipt": {
            "command": command,
            "spec_fingerprint": stable_fingerprint(spec),
            "inputs_fingerprint": stable_fingerprint(spec["inputs"]),
            "forbidden_actions_enforced": True,
        },
    }
    run_path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = validate_artifact(run_path, artifact_type="automation_run")
    if not result.ok:
        raise RuntimeError("generated automation run does not validate")
    return document, run_path

"""Agent run receipt, argv, patch, and policy-hash validation."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from .common import schema_path
from .models import FORMAT_CHECKER, ValidationIssue
from .registry import load_schema

def validate_agent_run_artifact(
    document: dict[str, Any], schema_dir: Path, artifact_path: Path
) -> list[ValidationIssue]:
    """Validate the embedded result and receipt-level consistency."""

    issues: list[ValidationIssue] = []
    if document["caller_provider"] == document["target_provider"]:
        issues.append(
            ValidationIssue("$.target_provider", "must differ from caller_provider")
        )
    expected_cwd = (
        "source_read_only" if document["mode"] == "read_only" else "detached_worktree"
    )
    if document["execution"]["cwd_strategy"] != expected_cwd:
        issues.append(
            ValidationIssue(
                "$.execution.cwd_strategy", f"must be {expected_cwd} for {document['mode']}"
            )
        )
    try:
        started = datetime.fromisoformat(
            document["execution"]["started_at"].replace("Z", "+00:00")
        )
        finished = datetime.fromisoformat(
            document["execution"]["finished_at"].replace("Z", "+00:00")
        )
        if started > finished:
            issues.append(
                ValidationIssue("$.execution.finished_at", "must not precede started_at")
            )
    except (TypeError, ValueError):
        pass
    if (
        document["status"] in {"complete", "blocked"}
        and document["execution"]["exit_code"] != 0
    ):
        issues.append(
            ValidationIssue(
                "$.execution.exit_code", "must be zero for complete or blocked runs"
            )
        )
    selection = document["model_selection"]
    current_policy_path = Path(__file__).resolve().parent.parent / "policies" / "agent-orchestration.v1.yaml"
    if current_policy_path.is_file():
        current_policy = yaml.safe_load(current_policy_path.read_text(encoding="utf-8"))
        current_policy_sha256 = hashlib.sha256(
            json.dumps(
                current_policy,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()
        if document["policy"]["sha256"] == current_policy_sha256:
            routing = current_policy["model_routing"]
            routing_sha256 = hashlib.sha256(
                json.dumps(
                    routing,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                ).encode("utf-8")
            ).hexdigest()
            if selection["routing_policy_sha256"] != routing_sha256:
                issues.append(
                    ValidationIssue(
                        "$.model_selection.routing_policy_sha256",
                        "must fingerprint the routing section of the recorded policy",
                    )
                )
            entry = routing["providers"][document["target_provider"]][
                selection["resolved_profile"]
            ]
            expected_effort = (
                entry["critical_effort"]
                if selection["resolved_workload_class"] == "critical"
                else entry["effort"]
            )
            expected_capabilities = sorted(set(entry["capabilities"]))
            if selection["requested_model"] != entry["model"]:
                issues.append(
                    ValidationIssue(
                        "$.model_selection.requested_model",
                        "must match the recorded policy profile",
                    )
                )
            if selection["reasoning_effort"] != expected_effort:
                issues.append(
                    ValidationIssue(
                        "$.model_selection.reasoning_effort",
                        "must match the recorded policy profile",
                    )
                )
            if selection["capabilities"] != expected_capabilities:
                issues.append(
                    ValidationIssue(
                        "$.model_selection.capabilities",
                        "must match the recorded policy profile",
                    )
                )
    argv = document["execution"]["sanitized_argv"]
    model_positions = [index for index, value in enumerate(argv) if value == "--model"]
    valid_model_position = (
        len(model_positions) == 1 and model_positions[0] + 1 < len(argv)
    )
    provider_started = document["execution"]["exit_code"] is not None
    if provider_started and not valid_model_position:
        issues.append(
            ValidationIssue("$.execution.sanitized_argv", "must contain one model selection")
        )
    elif valid_model_position and argv[model_positions[0] + 1] != selection["requested_model"]:
        issues.append(
            ValidationIssue(
                "$.model_selection.requested_model",
                "must match the model in sanitized_argv",
            )
        )
    effort = selection["reasoning_effort"]
    if valid_model_position and document["target_provider"] == "claude":
        effort_positions = [index for index, value in enumerate(argv) if value == "--effort"]
        if effort is None and effort_positions:
            issues.append(
                ValidationIssue(
                    "$.model_selection.reasoning_effort",
                    "must be null when Claude argv has no effort override",
                )
            )
        elif effort is not None and (
            len(effort_positions) != 1
            or effort_positions[0] + 1 >= len(argv)
            or argv[effort_positions[0] + 1] != effort
        ):
            issues.append(
                ValidationIssue(
                    "$.model_selection.reasoning_effort",
                    "must match the Claude effort in sanitized_argv",
                )
            )
    elif valid_model_position:
        expected_effort = f'model_reasoning_effort="{effort}"'
        if effort is None or expected_effort not in argv:
            issues.append(
                ValidationIssue(
                    "$.model_selection.reasoning_effort",
                    "must match the Codex reasoning config in sanitized_argv",
                )
            )
    result = document["result"]
    fingerprint = document["result_fingerprint"]
    if result is None:
        if document["status"] in {"complete", "blocked"}:
            issues.append(
                ValidationIssue("$.result", "is required for complete or blocked runs")
            )
        if fingerprint is not None:
            issues.append(
                ValidationIssue("$.result_fingerprint", "must be null when result is null")
            )
    else:
        result_schema = load_schema(schema_dir, "agent_result", 1)
        validator = Draft202012Validator(result_schema, format_checker=FORMAT_CHECKER)
        for error in sorted(
            validator.iter_errors(result), key=lambda item: list(item.absolute_path)
        ):
            path = schema_path(error)
            suffix = path[1:] if path.startswith("$") else f".{path}"
            issues.append(ValidationIssue(f"$.result{suffix}", error.message))
        if result.get("task_id") != document["task_id"]:
            issues.append(
                ValidationIssue("$.result.task_id", "must match the run task_id")
            )
        expected_status = {
            "complete": "complete",
            "blocked": "blocked",
        }.get(document["status"])
        if expected_status is not None and result.get("status") != expected_status:
            issues.append(
                ValidationIssue("$.result.status", "must match the run status")
            )
        payload = json.dumps(
            result, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
        expected_fingerprint = hashlib.sha256(payload).hexdigest()
        if fingerprint != expected_fingerprint:
            issues.append(
                ValidationIssue(
                    "$.result_fingerprint", "must fingerprint the embedded result"
                )
            )

    patch = document["patch"]
    if document["mode"] == "read_only" and patch is not None:
        issues.append(ValidationIssue("$.patch", "must be null for read_only runs"))
    if patch is not None:
        if result is None:
            issues.append(ValidationIssue("$.patch", "requires an embedded result"))
        elif patch["changed_paths"] != result["changed_paths"]:
            issues.append(
                ValidationIssue(
                    "$.patch.changed_paths", "must equal result.changed_paths"
                )
            )
        patch_path = Path(patch["path"])
        if not patch_path.is_absolute():
            issues.append(ValidationIssue("$.patch.path", "must be an absolute path"))
        elif (
            patch_path.name != f"agent-patch-{document['run_id']}.patch"
            or patch_path.parent.resolve() != artifact_path.parent.resolve()
        ):
            issues.append(
                ValidationIssue(
                    "$.patch.path", "must use the run ID beside the agent_run receipt"
                )
            )
        elif patch_path.is_symlink() or not patch_path.is_file():
            issues.append(
                ValidationIssue("$.patch.path", "must identify an existing regular file")
            )
        else:
            digest = hashlib.sha256()
            total = 0
            maximum = document["limits"]["max_output_bytes"]
            try:
                with patch_path.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        total += len(chunk)
                        if total > maximum:
                            issues.append(
                                ValidationIssue(
                                    "$.patch.path", "patch exceeds the recorded output limit"
                                )
                            )
                            break
                        digest.update(chunk)
            except OSError as exc:
                issues.append(
                    ValidationIssue("$.patch.path", f"cannot read patch evidence: {exc}")
                )
            else:
                if total <= maximum and digest.hexdigest() != patch["sha256"]:
                    issues.append(
                        ValidationIssue(
                            "$.patch.sha256", "must fingerprint the current patch bytes"
                        )
                    )
    elif (
        result is not None
        and document["status"] in {"complete", "blocked"}
        and document["mode"] == "worktree_patch"
        and result["changed_paths"]
    ):
        issues.append(
            ValidationIssue("$.patch", "is required when a worktree run changed files")
        )
    return issues


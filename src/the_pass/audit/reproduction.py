"""Allowlisted clean reproduction for custom strategy packages."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from the_pass.data.contracts import stable_fingerprint
from the_pass.strategy_runtime.config import load_json_object
from the_pass.validator import validate_artifact, validate_package


RUNNER_ID = "the_pass.backtest.run.v1"
ENV_ALLOWLIST = {"PATH", "LANG", "LC_ALL", "TMPDIR"}


class ReproductionError(ValueError):
    """Raised when a reproduction specification is unsafe or invalid."""


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_path(root: Path, value: str, *, directory: bool = False) -> Path:
    relative = PurePosixPath(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise ReproductionError(f"reproduction path is unsafe: {value}")
    path = root.joinpath(*relative.parts).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ReproductionError(f"reproduction path escapes package: {value}") from exc
    if directory and not path.is_dir():
        raise ReproductionError(f"reproduction directory is missing: {value}")
    if not directory and not path.is_file():
        raise ReproductionError(f"reproduction input is missing: {value}")
    return path


def load_reproduction_spec(package: Path) -> dict[str, Any]:
    package = package.resolve()
    path = package / "reproduction_spec.json"
    validation = validate_artifact(path, artifact_type="reproduction_spec")
    if not validation.ok:
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in validation.issues)
        raise ReproductionError(f"invalid reproduction spec: {details}")
    document = json.loads(path.read_text(encoding="utf-8"))
    if document["runner_id"] != RUNNER_ID:
        raise ReproductionError("reproduction runner is not allowlisted")
    if document["schema_version"] == 1 and document["network_allowed"] is not False:
        raise ReproductionError("legacy reproduction network policy is not allowlisted")
    seen = set()
    for row in document["input_fingerprints"]:
        value = row["path"]
        if value in seen:
            raise ReproductionError("reproduction input fingerprints contain duplicates")
        seen.add(value)
        if _digest(_safe_path(package, value)) != row["sha256"]:
            raise ReproductionError(f"reproduction input fingerprint changed: {value}")
    workspace = _safe_path(package, document["inputs"]["workspace"], directory=True)
    workspace_prefix = document["inputs"]["workspace"].rstrip("/") + "/"
    declared_workspace_files = {
        _safe_path(package, row["path"])
        for row in document["input_fingerprints"]
        if row["path"].startswith(workspace_prefix)
    }
    observed_workspace_files = set()
    for path in workspace.rglob("*"):
        if path.is_symlink():
            raise ReproductionError("reproduction workspace must not contain symlinks")
        if path.is_file():
            observed_workspace_files.add(path.resolve())
    if observed_workspace_files != declared_workspace_files:
        raise ReproductionError(
            "reproduction workspace files must exactly match declared fingerprints"
        )
    for value in document["expected_artifacts"]:
        relative = PurePosixPath(value)
        if relative.is_absolute() or ".." in relative.parts:
            raise ReproductionError(f"expected artifact path is unsafe: {value}")
    return document


def reproduce_package(
    package: Path,
    *,
    timeout_seconds: int = 120,
    environment: Mapping[str, str] | None = None,
    sandbox_launcher: Path | None = None,
    sandbox_policy: Path | None = None,
) -> dict[str, Any]:
    if isinstance(timeout_seconds, bool) or timeout_seconds <= 0 or timeout_seconds > 1800:
        raise ReproductionError("reproduction timeout_seconds must be in 1..1800")
    package = package.resolve()
    validation = validate_package(package)
    if not validation.ok:
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in validation.issues)
        raise ReproductionError(f"tracked package is invalid: {details}")
    spec = load_reproduction_spec(package)
    isolation = (
        {
            "mode": "trusted_local",
            "network_enforcement": "none",
            "filesystem_enforcement": "none",
            "resource_enforcement": "process_timeout_and_output_limit",
            "launcher_sha256": None,
        }
        if spec["schema_version"] == 1
        else dict(spec["isolation"])
    )
    runtime_mode = str(isolation["mode"])
    if runtime_mode == "hardened":
        if sandbox_launcher is None or sandbox_policy is None:
            raise ReproductionError(
                "hardened reproduction requires --sandbox-launcher and --sandbox-policy"
            )
        launcher = sandbox_launcher.expanduser().resolve(strict=True)
        if _digest(launcher) != isolation.get("launcher_sha256"):
            raise ReproductionError("sandbox launcher fingerprint does not match reproduction spec")
        policy = load_json_object(sandbox_policy, label="sandbox trust policy")
        if stable_fingerprint(policy) != isolation.get("policy_fingerprint"):
            raise ReproductionError(
                "sandbox trust policy fingerprint does not match reproduction spec"
            )
    elif sandbox_launcher is not None or sandbox_policy is not None:
        raise ReproductionError(
            "sandbox launcher and policy are valid only for hardened reproduction"
        )
    inputs = spec["inputs"]
    source_workspace = _safe_path(package, inputs["workspace"], directory=True)
    clean_environment = {
        key: value
        for key, value in dict(os.environ if environment is None else environment).items()
        if key in ENV_ALLOWLIST
    }
    with tempfile.TemporaryDirectory(prefix="the-pass-reproduce-") as tmp:
        root = Path(tmp)
        workspace = root / "workspace"
        shutil.copytree(source_workspace, workspace, symlinks=False)
        output = root / "package"
        argv = [
            sys.executable,
            "-m",
            "the_pass.cli",
            "backtest",
            "run",
            "--descriptor",
            str(_safe_path(package, inputs["descriptor"])),
            "--strategy-spec",
            str(_safe_path(package, inputs["strategy_spec"])),
            "--events",
            str(_safe_path(package, inputs["events"])),
            "--data-manifest",
            str(_safe_path(package, inputs["data_manifest"])),
            "--quality-report",
            str(_safe_path(package, inputs["quality_report"])),
            "--execution",
            str(_safe_path(package, inputs["execution"])),
            "--workspace-root",
            str(workspace),
            "--output",
            str(output),
            "--timeout-seconds",
            str(min(timeout_seconds, 60)),
            "--runtime-mode",
            runtime_mode,
            "--format",
            "json",
        ]
        if runtime_mode == "hardened":
            argv.extend(["--sandbox-launcher", str(sandbox_launcher.resolve())])
            argv.extend(["--sandbox-policy", str(sandbox_policy.resolve())])
        try:
            completed = subprocess.run(
                argv,
                cwd=root,
                env=clean_environment,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ReproductionError("clean reproduction timed out") from exc
        mismatches = []
        fingerprints = []
        for value in spec["expected_artifacts"]:
            expected_path = _safe_path(package, value)
            observed_path = output.joinpath(*PurePosixPath(value).parts)
            expected = _digest(expected_path)
            observed = _digest(observed_path) if observed_path.is_file() else None
            fingerprints.append({"path": value, "expected": expected, "observed": observed})
            if expected != observed:
                mismatches.append(value)
        rebuilt_validation = validate_package(output) if output.is_dir() else None
        rebuilt_valid = rebuilt_validation is not None and rebuilt_validation.ok
        status = (
            "pass"
            if completed.returncode == 0 and rebuilt_valid and not mismatches
            else "blocked"
        )
        return {
            "schema_version": 1,
            "runner_id": RUNNER_ID,
            "clean_temporary_directory": True,
            "isolation": isolation,
            "exit_code": completed.returncode,
            "stdout_sha256": hashlib.sha256(completed.stdout).hexdigest(),
            "stderr_sha256": hashlib.sha256(completed.stderr).hexdigest(),
            "fingerprints": fingerprints,
            "mismatches": mismatches,
            "rebuilt_package_valid": rebuilt_valid,
            "status": status,
        }

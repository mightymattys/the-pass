"""Signed reviewer provenance for promotion decisions."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .validator import load_document, validate_artifact


ATTESTATION_KEY_ENV = "THE_PASS_REVIEW_ATTESTATION_KEY"
ATTESTABLE_GATES = ("research_gate", "paper_gate", "risk_review")


class AttestationError(ValueError):
    """Raised when reviewer provenance cannot be signed or verified."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(document: Mapping[str, Any]) -> bytes:
    unsigned = {key: value for key, value in document.items() if key != "signature"}
    return json.dumps(
        unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _validated_key(key: str | bytes | None) -> bytes:
    raw = key if key is not None else os.environ.get(ATTESTATION_KEY_ENV)
    if raw is None:
        raise AttestationError(f"{ATTESTATION_KEY_ENV} is required")
    value = raw.encode("utf-8") if isinstance(raw, str) else raw
    if len(value) < 32:
        raise AttestationError("review attestation key must contain at least 32 bytes")
    return value


def attestation_path(package: Path, gate: str) -> Path:
    return package.resolve() / f"reviewer_attestation.{gate}.json"


def review_task_path(package: Path, gate: str) -> Path:
    if gate not in ATTESTABLE_GATES:
        raise AttestationError("only non-live promotion gates have review task evidence")
    stem = "findings" if gate == "research_gate" else f"audit_report.{gate}"
    matches = [
        package.resolve() / f"{stem}{extension}"
        for extension in (".json", ".yaml", ".yml")
        if (package.resolve() / f"{stem}{extension}").is_file()
    ]
    if len(matches) != 1:
        raise AttestationError(f"review task evidence is missing or ambiguous: {stem}")
    return matches[0]


def create_reviewer_attestation(
    *,
    gate: str,
    package_id: str,
    reviewer: str,
    principal_type: str,
    provider: str,
    model: str,
    run_id: str,
    author_provider: str,
    reviewer_provider: str,
    evidence: Mapping[str, str],
    key: str | bytes | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    if gate not in ATTESTABLE_GATES:
        raise AttestationError("only non-live promotion gates can be attested")
    if principal_type not in {"provider", "human"}:
        raise AttestationError("principal_type must be provider or human")
    values = (reviewer, provider, model, run_id, author_provider, reviewer_provider)
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise AttestationError("attestation identities and provenance must be non-empty")
    if principal_type == "provider" and author_provider == reviewer_provider:
        raise AttestationError("automated reviewer provider must differ from author provider")
    required_evidence = {
        "state_before_sha256",
        "state_after_sha256",
        "stdout_sha256",
        "stderr_sha256",
        "task_sha256",
    }
    if set(evidence) != required_evidence or any(
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
        for value in evidence.values()
    ):
        raise AttestationError("attestation requires exactly five SHA-256 evidence values")
    signing_key = _validated_key(key)
    key_id = f"key_{hashlib.sha256(signing_key).hexdigest()[:16]}"
    document: dict[str, Any] = {
        "schema_version": 1,
        "id": f"att_{gate}_{package_id[4:]}_{key_id[4:12]}",
        "created_at": created_at or _utc_now(),
        "gate_id": gate,
        "package_id": package_id,
        "reviewer": reviewer,
        "principal": {
            "type": principal_type,
            "provider": provider,
            "model": model,
            "run_id": run_id,
        },
        "separation": {
            "author_provider": author_provider,
            "reviewer_provider": reviewer_provider,
        },
        "evidence": dict(evidence),
        "key_id": key_id,
    }
    document["signature"] = hmac.new(
        signing_key, _canonical(document), hashlib.sha256
    ).hexdigest()
    return document


def write_reviewer_attestation(path: Path, document: Mapping[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(document, indent=2, sort_keys=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary_name, path)
        except FileExistsError as exc:
            raise AttestationError("reviewer attestation already exists") from exc
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def verify_reviewer_attestation(
    path: Path,
    *,
    gate: str,
    package_id: str,
    reviewer: str,
    key: str | bytes | None = None,
) -> tuple[dict[str, Any] | None, list[str]]:
    validation = validate_artifact(path, artifact_type="reviewer_attestation")
    if not validation.ok:
        return None, [
            f"reviewer_attestation:{issue.path}: {issue.message}"
            for issue in validation.issues
        ]
    document = load_document(path)
    if not isinstance(document, dict):
        return None, ["reviewer attestation must be an object"]
    blockers: list[str] = []
    if document.get("gate_id") != gate:
        blockers.append("reviewer attestation gate does not match")
    if document.get("package_id") != package_id:
        blockers.append("reviewer attestation package_id does not match")
    if document.get("reviewer") != reviewer:
        blockers.append("reviewer attestation reviewer does not match")
    principal = document.get("principal", {})
    separation = document.get("separation", {})
    if (
        principal.get("type") == "provider"
        and separation.get("author_provider") == separation.get("reviewer_provider")
    ):
        blockers.append("automated reviewer provider is not independent")
    try:
        signing_key = _validated_key(key)
    except AttestationError as exc:
        blockers.append(str(exc))
        return document, blockers
    expected_key_id = f"key_{hashlib.sha256(signing_key).hexdigest()[:16]}"
    if document.get("key_id") != expected_key_id:
        blockers.append("reviewer attestation key_id does not match")
    expected = hmac.new(signing_key, _canonical(document), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(str(document.get("signature", "")), expected):
        blockers.append("reviewer attestation signature does not verify")
    return document, blockers

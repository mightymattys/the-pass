"""Publicly verifiable reviewer provenance for promotion decisions."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .data.contracts import stable_fingerprint
from .validator import load_document, validate_artifact


ATTESTATION_KEY_ENV = "THE_PASS_REVIEW_ATTESTATION_KEY"
SIGNING_KEY_ENV = "THE_PASS_REVIEW_SIGNING_KEY"
ATTESTABLE_GATES = ("research_gate", "paper_gate", "risk_review")


class AttestationError(ValueError):
    """Raised when reviewer provenance cannot be signed or verified."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise AttestationError("attestation time must be RFC3339") from exc
    if parsed.tzinfo is None:
        raise AttestationError("attestation time must include a timezone")
    return parsed.astimezone(timezone.utc)


def _canonical(document: Mapping[str, Any]) -> bytes:
    unsigned = {key: value for key, value in document.items() if key != "signature"}
    return json.dumps(
        unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")


def _validated_legacy_key(key: str | bytes | None) -> bytes:
    raw = key if key is not None else os.environ.get(ATTESTATION_KEY_ENV)
    if raw is None:
        raise AttestationError(f"{ATTESTATION_KEY_ENV} is required")
    value = raw.encode("utf-8") if isinstance(raw, str) else raw
    if len(value) < 32:
        raise AttestationError("review attestation key must contain at least 32 bytes")
    return value


def _decode_base64(value: str, *, label: str, length: int) -> bytes:
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AttestationError(f"{label} must be canonical base64") from exc
    if len(raw) != length or base64.b64encode(raw).decode("ascii") != value:
        raise AttestationError(f"{label} must encode exactly {length} bytes")
    return raw


def _private_key(value: str | bytes | None) -> Ed25519PrivateKey:
    raw_value = value if value is not None else os.environ.get(SIGNING_KEY_ENV)
    if raw_value is None:
        raise AttestationError(f"{SIGNING_KEY_ENV} is required")
    if isinstance(raw_value, bytes):
        raw = raw_value
    else:
        raw = _decode_base64(raw_value, label="review signing key", length=32)
    if len(raw) != 32:
        raise AttestationError("review signing key must contain exactly 32 raw bytes")
    return Ed25519PrivateKey.from_private_bytes(raw)


def _public_bytes(key: Ed25519PrivateKey | Ed25519PublicKey) -> bytes:
    public = key.public_key() if isinstance(key, Ed25519PrivateKey) else key
    return public.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def _key_id(public_key: bytes) -> str:
    return f"key_{hashlib.sha256(public_key).hexdigest()[:16]}"


def generate_reviewer_keypair() -> tuple[str, str]:
    private = Ed25519PrivateKey.generate()
    private_raw = private.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return (
        base64.b64encode(private_raw).decode("ascii"),
        base64.b64encode(_public_bytes(private)).decode("ascii"),
    )


def create_reviewer_key_registry(
    *,
    registry_id: str,
    reviewer: str,
    principal_type: str,
    provider: str,
    public_key: str,
    valid_from: str,
    valid_until: str,
    created_at: str | None = None,
    revoked_at: str | None = None,
) -> dict[str, Any]:
    values = (registry_id, reviewer, provider)
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise AttestationError("registry identity fields must be non-empty")
    if principal_type not in {"provider", "human"}:
        raise AttestationError("principal_type must be provider or human")
    raw_public = _decode_base64(public_key, label="review public key", length=32)
    start = _parse_time(valid_from)
    end = _parse_time(valid_until)
    if start >= end:
        raise AttestationError("review key valid_from must be before valid_until")
    if revoked_at is not None and _parse_time(revoked_at) < start:
        raise AttestationError("review key cannot be revoked before valid_from")
    return {
        "schema_version": 1,
        "id": registry_id.strip(),
        "created_at": created_at or _utc_now(),
        "keys": [
            {
                "key_id": _key_id(raw_public),
                "reviewer": reviewer.strip(),
                "principal_type": principal_type,
                "provider": provider.strip(),
                "public_key": public_key,
                "valid_from": valid_from,
                "valid_until": valid_until,
                "revoked_at": revoked_at,
            }
        ],
    }


def write_private_signing_key(path: Path, private_key: str) -> None:
    _decode_base64(private_key, label="review signing key", length=32)
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="ascii") as handle:
        handle.write(private_key + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def attestation_path(package: Path, gate: str) -> Path:
    return package.resolve() / f"reviewer_attestation.{gate}.json"


def registry_snapshot_path(package: Path, gate: str) -> Path:
    return package.resolve() / f"reviewer_key_registry.{gate}.json"


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


def _evidence(evidence: Mapping[str, str]) -> dict[str, str]:
    required = {
        "state_before_sha256",
        "state_after_sha256",
        "stdout_sha256",
        "stderr_sha256",
        "task_sha256",
    }
    if set(evidence) != required or any(
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
        for value in evidence.values()
    ):
        raise AttestationError("attestation requires exactly five SHA-256 evidence values")
    return dict(evidence)


def _legacy_attestation(
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
    key: str | bytes | None,
    created_at: str | None,
) -> dict[str, Any]:
    signing_key = _validated_legacy_key(key)
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
        "evidence": _evidence(evidence),
        "key_id": key_id,
    }
    document["signature"] = hmac.new(
        signing_key, _canonical(document), hashlib.sha256
    ).hexdigest()
    return document


def _registry_entry(
    registry: Mapping[str, Any],
    *,
    private: Ed25519PrivateKey,
    reviewer: str,
    principal_type: str,
    provider: str,
) -> dict[str, Any]:
    public = _public_bytes(private)
    key_id = _key_id(public)
    matches = [
        item
        for item in registry.get("keys", [])
        if isinstance(item, dict)
        and item.get("key_id") == key_id
        and item.get("reviewer") == reviewer
        and item.get("principal_type") == principal_type
        and item.get("provider") == provider
    ]
    if len(matches) != 1:
        raise AttestationError("signing key has no unique matching reviewer registry entry")
    if _decode_base64(
        str(matches[0]["public_key"]), label="review public key", length=32
    ) != public:
        raise AttestationError("review registry public key does not match signing key")
    return dict(matches[0])


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
    private_key: str | bytes | None = None,
    registry: Mapping[str, Any] | None = None,
    key: str | bytes | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Create v2 Ed25519 evidence, or legacy v1 only for explicit compatibility callers."""

    if gate not in ATTESTABLE_GATES:
        raise AttestationError("only non-live promotion gates can be attested")
    if principal_type not in {"provider", "human"}:
        raise AttestationError("principal_type must be provider or human")
    values = (reviewer, provider, model, run_id, author_provider, reviewer_provider)
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise AttestationError("attestation identities and provenance must be non-empty")
    if principal_type == "provider" and author_provider == reviewer_provider:
        raise AttestationError("automated reviewer provider must differ from author provider")
    if registry is None:
        if private_key is not None:
            raise AttestationError("v2 reviewer attestation requires a public key registry")
        return _legacy_attestation(
            gate=gate,
            package_id=package_id,
            reviewer=reviewer,
            principal_type=principal_type,
            provider=provider,
            model=model,
            run_id=run_id,
            author_provider=author_provider,
            reviewer_provider=reviewer_provider,
            evidence=evidence,
            key=key,
            created_at=created_at,
        )
    if key is not None:
        raise AttestationError("legacy HMAC key cannot sign a v2 reviewer attestation")
    private = _private_key(private_key)
    entry = _registry_entry(
        registry,
        private=private,
        reviewer=reviewer,
        principal_type=principal_type,
        provider=provider,
    )
    timestamp = created_at or _utc_now()
    moment = _parse_time(timestamp)
    if not (_parse_time(entry["valid_from"]) <= moment <= _parse_time(entry["valid_until"])):
        raise AttestationError("review signing key is outside its validity interval")
    revoked = entry.get("revoked_at")
    if revoked is not None and moment >= _parse_time(revoked):
        raise AttestationError("review signing key was revoked at attestation time")
    registry_fingerprint = stable_fingerprint(registry)
    document: dict[str, Any] = {
        "schema_version": 2,
        "id": f"att_{gate}_{package_id[4:]}_{entry['key_id'][4:12]}",
        "created_at": timestamp,
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
        "evidence": _evidence(evidence),
        "signature_algorithm": "ed25519",
        "signer": {
            "key_id": entry["key_id"],
            "public_key": entry["public_key"],
            "registry_id": registry["id"],
            "registry_fingerprint": registry_fingerprint,
        },
    }
    document["signature"] = base64.b64encode(private.sign(_canonical(document))).decode(
        "ascii"
    )
    return document


def _write_create_only(path: Path, payload: str, *, mode: int = 0o600) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary_name, path)
        except FileExistsError as exc:
            raise AttestationError(f"public evidence already exists: {path.name}") from exc
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def write_reviewer_attestation(path: Path, document: Mapping[str, Any]) -> None:
    _write_create_only(path, json.dumps(document, indent=2, sort_keys=True) + "\n")


def write_registry_snapshot(path: Path, document: Mapping[str, Any]) -> None:
    payload = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if path.is_file():
        if path.read_text(encoding="utf-8") != payload:
            raise AttestationError("reviewer key registry snapshot already differs")
        return
    _write_create_only(path, payload)


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
    if document.get("schema_version") == 1:
        if key is not None:
            try:
                legacy_key = _validated_legacy_key(key)
                expected = hmac.new(
                    legacy_key, _canonical(document), hashlib.sha256
                ).hexdigest()
                if not hmac.compare_digest(str(document.get("signature", "")), expected):
                    blockers.append("legacy reviewer attestation signature does not verify")
            except AttestationError as exc:
                blockers.append(str(exc))
        blockers.append("legacy HMAC reviewer attestation cannot authorize a new gate pass")
        return document, blockers

    registry_path = registry_snapshot_path(path.parent, gate)
    registry_validation = validate_artifact(
        registry_path, artifact_type="reviewer_key_registry"
    )
    if not registry_validation.ok:
        blockers.extend(
            f"reviewer_key_registry:{issue.path}: {issue.message}"
            for issue in registry_validation.issues
        )
        return document, blockers
    registry = load_document(registry_path)
    if not isinstance(registry, dict):
        blockers.append("reviewer key registry must be an object")
        return document, blockers
    signer = document.get("signer", {})
    if signer.get("registry_id") != registry.get("id"):
        blockers.append("reviewer attestation registry ID does not match")
    if signer.get("registry_fingerprint") != stable_fingerprint(registry):
        blockers.append("reviewer attestation registry fingerprint does not match")
    entries = [
        item
        for item in registry.get("keys", [])
        if isinstance(item, dict) and item.get("key_id") == signer.get("key_id")
    ]
    if len(entries) != 1:
        blockers.append("reviewer attestation signer key is not unique in the registry")
        return document, blockers
    entry = entries[0]
    expected_binding = {
        "reviewer": reviewer,
        "principal_type": principal.get("type"),
        "provider": principal.get("provider"),
        "public_key": signer.get("public_key"),
    }
    for field, expected in expected_binding.items():
        if entry.get(field) != expected:
            blockers.append(f"reviewer registry {field} does not match attestation")
    try:
        public_raw = _decode_base64(
            str(signer.get("public_key", "")), label="review public key", length=32
        )
        if signer.get("key_id") != _key_id(public_raw):
            blockers.append("reviewer attestation key ID does not match public key")
        moment = _parse_time(str(document.get("created_at", "")))
        if not (
            _parse_time(str(entry.get("valid_from", "")))
            <= moment
            <= _parse_time(str(entry.get("valid_until", "")))
        ):
            blockers.append("reviewer attestation key is outside its validity interval")
        revoked = entry.get("revoked_at")
        if revoked is not None and moment >= _parse_time(str(revoked)):
            blockers.append("reviewer attestation key was revoked at signing time")
        signature = _decode_base64(
            str(document.get("signature", "")), label="review signature", length=64
        )
        Ed25519PublicKey.from_public_bytes(public_raw).verify(
            signature, _canonical(document)
        )
    except InvalidSignature:
        blockers.append("reviewer attestation signature does not verify")
    except AttestationError as exc:
        blockers.append(str(exc))
    return document, blockers

"""Locked public execution contracts with no external transaction capability."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Protocol

from .data.contracts import stable_fingerprint


SENSITIVE_CONFIG_KEYS = {"secret", "api_key", "private_key", "credential", "token"}


class ExecutionGateway(Protocol):
    transport_available: bool

    def prove_dry_run(self, intent: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]: ...


@dataclass(frozen=True)
class HumanDecision:
    reviewer: str
    decision: str = "blocked"
    accepted_live_capability_adr: bool = False
    grants_live_approval: bool = False

    def __post_init__(self) -> None:
        if self.decision != "blocked" or self.accepted_live_capability_adr or self.grants_live_approval:
            raise ValueError("public HumanDecision is permanently locked")


class LockedExecutionGateway:
    transport_available = False

    def prove_dry_run(self, intent: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": 2,
            "id": f"dry-run-{stable_fingerprint(intent)[:16]}",
            "created_at": "2026-07-10T00:00:00Z",
            "gateway": "locked_public_core",
            "config_hash": stable_fingerprint(config),
            "intent_fingerprint": stable_fingerprint(intent),
            "external_side_effects": False,
            "transport_available": False,
            "result": "blocked",
        }


def build_config_diff(before: Mapping[str, Any], after: Mapping[str, Any]) -> dict[str, Any]:
    keys = set(before) | set(after)
    if any(any(sensitive in key.lower() for sensitive in SENSITIVE_CONFIG_KEYS) for key in keys):
        raise ValueError("config diff cannot contain secret-like keys")
    changes = [
        {"field": key, "before": before.get(key), "after": after.get(key)}
        for key in sorted(keys)
        if before.get(key) != after.get(key)
    ]
    return {
        "schema_version": 2,
        "id": f"config-diff-{stable_fingerprint([before, after])[:16]}",
        "created_at": "2026-07-10T00:00:00Z",
        "before_hash": stable_fingerprint(before),
        "after_hash": stable_fingerprint(after),
        "changes": changes,
        "review_required": True,
        "secrets_present": False,
    }


def build_locked_live_risk_contract(account_equity: Decimal, policy_hash: str) -> dict[str, Any]:
    if account_equity <= 0:
        raise ValueError("account equity must be positive")
    if len(policy_hash) != 64 or any(char not in "0123456789abcdefABCDEF" for char in policy_hash):
        raise ValueError("policy_hash must be a SHA-256 hex digest")
    return {
        "schema_version": 2,
        "id": f"locked-live-risk-{policy_hash[:16]}",
        "created_at": "2026-07-10T00:00:00Z",
        "account_equity": float(account_equity),
        "micro_notional_cap": float(min(Decimal(100), account_equity * Decimal("0.0025"))),
        "daily_loss_cap": float(min(Decimal(25), account_equity * Decimal("0.0010"))),
        "max_leverage": 1.0,
        "freeze_conditions": [
            "loss breach",
            "divergence breach",
            "data health breach",
            "operational safety breach",
        ],
        "policy_hash": policy_hash,
        "locked": True,
    }

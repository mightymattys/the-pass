"""Adapter contract checks for market-specific The Pass adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


ADAPTER_MODES = ("diagnostic", "research", "paper", "live-capable")
REQUIRED_PROVIDER_FIELDS = ("id", "type", "license", "fields", "limitations")
REQUIRED_PROVIDER_REVIEW_FIELDS = (
    "license",
    "redistribution",
    "authentication",
    "retention",
    "deterministic_replay",
    "limitations",
)
REQUIRED_ENGINE_FIELDS = ("name", "role", "limitations")
REQUIRED_POLICY_FIELDS = ("timestamp", "cost_model", "fill_model", "risk_model", "settlement")
UNKNOWN_VALUES = {"", "unknown", "tbd", "todo", "n/a", "none yet"}


@dataclass(frozen=True)
class AdapterContractIssue:
    """A strict adapter-contract issue converted by the artifact validator."""

    path: str
    message: str
    severity: str = "error"


def is_missing_text(value: Any) -> bool:
    return not isinstance(value, str) or value.strip().lower() in UNKNOWN_VALUES


def is_string_list(value: Any) -> bool:
    return isinstance(value, list) and bool(value) and all(isinstance(item, str) and item.strip() for item in value)


def require_object(document: dict[str, Any], field: str, issues: list[AdapterContractIssue]) -> dict[str, Any] | None:
    value = document.get(field)
    if not isinstance(value, dict):
        issues.append(AdapterContractIssue(f"$.{field}", "must be an object"))
        return None
    return value


def validate_providers(document: dict[str, Any], issues: list[AdapterContractIssue]) -> None:
    providers = document.get("providers")
    if not isinstance(providers, list) or not providers:
        issues.append(AdapterContractIssue("$.providers", "must contain at least one provider"))
        return

    for index, provider in enumerate(providers):
        path = f"$.providers[{index}]"
        if not isinstance(provider, dict):
            issues.append(AdapterContractIssue(path, "must be an object"))
            continue

        for field in REQUIRED_PROVIDER_FIELDS:
            if field not in provider:
                issues.append(AdapterContractIssue(f"{path}.{field}", "is required"))

        for field in ("id", "type", "license"):
            if is_missing_text(provider.get(field)):
                issues.append(AdapterContractIssue(f"{path}.{field}", "must be explicit"))

        if not is_string_list(provider.get("fields")):
            issues.append(AdapterContractIssue(f"{path}.fields", "must contain at least one field"))

        limitations = provider.get("limitations")
        if not isinstance(limitations, list):
            issues.append(AdapterContractIssue(f"{path}.limitations", "must be an array"))


def validate_provider_review(document: dict[str, Any], mode: str, issues: list[AdapterContractIssue]) -> None:
    review = require_object(document, "provider_review", issues)
    if review is None:
        return

    for field in REQUIRED_PROVIDER_REVIEW_FIELDS:
        if field not in review:
            issues.append(AdapterContractIssue(f"$.provider_review.{field}", "is required"))

    for field in ("license", "redistribution", "authentication", "retention"):
        if is_missing_text(review.get(field)):
            issues.append(AdapterContractIssue(f"$.provider_review.{field}", "must be explicit"))

    if not isinstance(review.get("deterministic_replay"), bool):
        issues.append(AdapterContractIssue("$.provider_review.deterministic_replay", "must be boolean"))

    limitations = review.get("limitations")
    if not isinstance(limitations, list):
        issues.append(AdapterContractIssue("$.provider_review.limitations", "must be an array"))

    if mode in {"research", "paper", "live-capable"} and review.get("deterministic_replay") is not True:
        issues.append(
            AdapterContractIssue(
                "$.provider_review.deterministic_replay",
                "must be true for research, paper, or live-capable adapters",
            )
        )


def validate_engine(document: dict[str, Any], issues: list[AdapterContractIssue]) -> None:
    engine = require_object(document, "engine", issues)
    if engine is None:
        return

    for field in REQUIRED_ENGINE_FIELDS:
        if field not in engine:
            issues.append(AdapterContractIssue(f"$.engine.{field}", "is required"))

    for field in ("name", "role"):
        if is_missing_text(engine.get(field)):
            issues.append(AdapterContractIssue(f"$.engine.{field}", "must be explicit"))

    if not isinstance(engine.get("limitations"), list):
        issues.append(AdapterContractIssue("$.engine.limitations", "must be an array"))


def validate_policies(document: dict[str, Any], issues: list[AdapterContractIssue]) -> None:
    policies = require_object(document, "policies", issues)
    if policies is None:
        return

    for field in REQUIRED_POLICY_FIELDS:
        if field not in policies:
            issues.append(AdapterContractIssue(f"$.policies.{field}", "is required"))
        elif is_missing_text(policies.get(field)):
            issues.append(AdapterContractIssue(f"$.policies.{field}", "must be explicit"))


def validate_mode_safety(document: dict[str, Any], mode: str, issues: list[AdapterContractIssue]) -> None:
    safety = require_object(document, "safety", issues)
    if safety is None:
        return

    if mode == "diagnostic":
        for field in ("live_trading_enabled", "real_order_path_available", "credentials_required"):
            if safety.get(field) is not False:
                issues.append(AdapterContractIssue(f"$.safety.{field}", "must be false for diagnostic adapters"))

    if mode == "live-capable":
        live = require_object(document, "live_readiness", issues)
        if live is None:
            return
        for field in ("accepted_adr", "credential_boundary", "risk_envelope", "rollback_plan", "human_approval"):
            if is_missing_text(live.get(field)):
                issues.append(AdapterContractIssue(f"$.live_readiness.{field}", "must be explicit"))


def validate_adapter_contract(document: dict[str, Any]) -> list[AdapterContractIssue]:
    """Return strict adapter-contract issues beyond JSON Schema shape."""

    issues: list[AdapterContractIssue] = []

    asset_classes = document.get("asset_classes")
    if not is_string_list(asset_classes):
        issues.append(AdapterContractIssue("$.asset_classes", "must contain at least one asset class"))

    mode = document.get("mode")
    if not isinstance(mode, str) or mode not in ADAPTER_MODES:
        issues.append(AdapterContractIssue("$.mode", f"must be one of: {', '.join(ADAPTER_MODES)}"))
        mode = ""

    validate_providers(document, issues)
    validate_provider_review(document, mode, issues)
    validate_engine(document, issues)
    validate_policies(document, issues)
    validate_mode_safety(document, mode, issues)

    return issues

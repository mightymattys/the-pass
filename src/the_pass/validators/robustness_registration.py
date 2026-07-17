"""Robustness registration, policy binding, and ledger preflight."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import yaml

from ..data.contracts import stable_fingerprint
from .models import ValidationIssue

def validate_registration_policy_and_ledger(
    document: dict[str, Any],
    ledger_path: Path | None,
    issues: list[ValidationIssue],
) -> tuple[
    dict[str, Any],
    list[Any],
    int,
    int,
    Any,
    bool,
    dict[str, float | str],
    bool,
    dict[str, Any],
    int,
    bool,
]:
    registration = document["registration"]
    registration_core = {
        key: value
        for key, value in registration.items()
        if key != "registration_fingerprint"
    }
    if registration["registration_fingerprint"] != stable_fingerprint(
        registration_core
    ):
        issues.append(
            ValidationIssue(
                "$.registration.registration_fingerprint",
                "does not match the registered experiment inputs",
            )
        )
    report_core = {
        key: value
        for key, value in document.items()
        if key != "report_fingerprint"
    }
    if document["report_fingerprint"] != stable_fingerprint(report_core):
        issues.append(
            ValidationIssue(
                "$.report_fingerprint",
                "does not match the robustness report contents",
            )
        )

    variants = registration["variants"]
    variant_count = len(variants)
    null_index = registration["null_variant_index"]
    reference_index = registration["reference_variant_index"]
    if null_index >= variant_count:
        issues.append(
            ValidationIssue(
                "$.registration.null_variant_index",
                "must identify a registered variant",
            )
        )
    if reference_index >= variant_count or reference_index == null_index:
        issues.append(
            ValidationIssue(
                "$.registration.reference_variant_index",
                "must identify a non-null registered variant",
            )
        )
    null_variant = variants[null_index] if 0 <= null_index < variant_count else {}
    null_kind = null_variant.get("kind") if isinstance(null_variant, dict) else None
    structural_null_valid = (
        isinstance(null_variant, dict)
        and null_variant.get("role") == "null"
        and null_kind in {"flat", "seeded_random"}
    )
    if not structural_null_valid:
        issues.append(
            ValidationIssue(
                "$.registration.variants",
                "null variant must declare role=null and kind=flat or seeded_random",
            )
        )
    elif null_kind == "seeded_random":
        seed = null_variant.get("seed")
        if isinstance(seed, bool) or not isinstance(seed, int):
            structural_null_valid = False
            issues.append(
                ValidationIssue(
                    f"$.registration.variants[{null_index}].seed",
                    "seeded_random null variant requires an integer seed",
                )
            )
        reference_variant = variants[reference_index]
        metadata = {"role", "kind", "seed"}
        overlap = (set(null_variant) - metadata) & (
            set(reference_variant) - metadata
        )
        if overlap:
            structural_null_valid = False
            issues.append(
                ValidationIssue(
                    f"$.registration.variants[{null_index}]",
                    "seeded_random null variant shares strategy keys with the reference variant: "
                    + ", ".join(sorted(overlap)),
                )
            )
        issues.append(
            ValidationIssue(
                f"$.registration.variants[{null_index}]",
                "seeded_random is diagnostic only and cannot support promotion until a trusted framework-side generator exists",
                "warning",
            )
        )

    policy_path = (
        Path(__file__).resolve().parent.parent / "policies" / "risk-policies.v1.yaml"
    )
    policy_bytes = policy_path.read_bytes()
    policy = yaml.safe_load(policy_bytes)
    policy_values = policy["asset_classes"]["crypto_intraday"]
    packaged_thresholds = {
        "maximum_pbo": float(policy_values["maximum_pbo"]),
        "minimum_dsr": float(policy_values["minimum_dsr"]),
        "maximum_reality_check_pvalue": float(
            policy_values["maximum_reality_check_pvalue"]
        ),
        "policy_sha256": hashlib.sha256(policy_bytes).hexdigest(),
    }
    reported_thresholds = document["statistics"]["thresholds"]
    policy_binding_valid = reported_thresholds == packaged_thresholds
    if document.get("promotion_eligible") is True and not policy_binding_valid:
        issues.append(
            ValidationIssue(
                "$.statistics.thresholds.policy_sha256",
                "promotion requires the packaged risk policy fingerprint and thresholds",
            )
        )

    ledger_registration = document.get("ledger_registration")
    reported_attempt = (
        ledger_registration.get("attempt", 1)
        if isinstance(ledger_registration, dict)
        else 1
    )
    ledger_attempt: int | None = None
    effective_trial_count = variant_count
    ledger_registration_valid = ledger_path is None
    requires_ledger = (
        document.get("promotion_eligible") is True and ledger_path is not None
    )
    if requires_ledger:
        from ..ledger import LedgerError, read_ledger_entries, verify_ledger_entries

        try:
            operator_entries = read_ledger_entries(ledger_path)
        except (OSError, ValueError, LedgerError) as exc:
            operator_entries = []
            ledger_issues = [ValidationIssue(str(ledger_path), str(exc))]
        else:
            ledger_issues = verify_ledger_entries(operator_entries)
        if ledger_issues:
            issues.extend(
                ValidationIssue(
                    f"$.ledger_registration.{issue.path}", issue.message
                )
                for issue in ledger_issues
            )
        else:
            matching = [
                entry
                for entry in operator_entries
                if entry.get("entry_kind") == "robustness_registration"
                and entry.get("events_fingerprint")
                == registration.get("events_fingerprint")
                and entry.get("descriptor_fingerprint")
                == registration.get("descriptor_fingerprint")
            ]
            if matching:
                latest = matching[-1]
                ledger_attempt = int(latest["attempt"])
                effective_trial_count = sum(
                    int(entry["variant_count"]) for entry in matching
                )
                receipt = next(
                    (
                        entry
                        for entry in matching
                        if entry.get("registration_fingerprint")
                        == registration.get("registration_fingerprint")
                        and entry.get("attempt") == reported_attempt
                    ),
                    None,
                )
                ledger_registration_valid = (
                    receipt is not None
                    and isinstance(ledger_registration, dict)
                    and ledger_registration.get("entry_hash")
                    == receipt.get("entry_hash")
                    and reported_attempt == ledger_attempt
                    and ledger_registration.get("effective_trial_count")
                    == effective_trial_count
                )
            if not ledger_registration_valid:
                issues.append(
                    ValidationIssue(
                        "$.ledger_registration",
                        "must match the latest ledger-backed registration attempt for the events and descriptor key",
                    )
                )
    return (
        registration,
        variants,
        variant_count,
        null_index,
        null_kind,
        structural_null_valid,
        packaged_thresholds,
        policy_binding_valid,
        reported_thresholds,
        effective_trial_count,
        ledger_registration_valid,
    )

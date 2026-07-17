"""Artifact type detection by filename and distinctive key subsets."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .registry import ARTIFACT_TYPES

def detect_artifact_type(path: Path, document: Any) -> str | None:
    """Detect artifact type from filename first, then from distinctive keys."""

    stem = path.stem
    if stem in ARTIFACT_TYPES:
        return stem

    if not isinstance(document, dict):
        return None

    keys = set(document)
    if {"mode", "asset_classes", "providers", "engine", "policies", "safety"} <= keys:
        return "adapter"
    if {"type", "priority", "status", "claim", "evidence", "required_tests"} <= keys:
        return "source_note"
    if {
        "status",
        "proposed_name",
        "source_notes",
        "edge",
        "market",
        "test",
        "risks",
        "kill_when",
        "blockers",
    } <= keys:
        return "hypothesis"
    if {
        "market",
        "edge",
        "data",
        "signal",
        "execution",
        "risk",
        "validation",
        "gates",
    } <= keys:
        return "strategy_spec"
    if {
        "dataset_name",
        "source",
        "coverage",
        "schema",
        "quality",
        "fingerprint",
    } <= keys:
        return "data_manifest"
    if {"strategy_spec", "code_version", "data_manifest", "outputs", "safety"} <= keys:
        return "run_receipt"
    if {"sample", "gross_metrics", "net_metrics", "robustness"} <= keys:
        return "metrics_report"
    if {
        "source_package_id",
        "registration",
        "matrix",
        "cells",
        "statistics",
        "validation",
        "promotion_eligible",
        "report_fingerprint",
    } <= keys:
        return "robustness_report"
    if {"gross_pnl", "costs", "net_pnl", "assumptions"} <= keys:
        return "cost_waterfall"
    if {"verdict", "gate_results", "evidence", "risks", "next_action"} <= keys:
        return "verdict_report"
    if {
        "strategy_spec",
        "mode",
        "sample",
        "variants",
        "baseline",
        "costs",
        "results",
        "decision",
        "safety",
    } <= keys:
        return "screen_report"
    if {"package", "reviewer", "target_gate", "findings", "summary"} <= keys:
        return "findings"
    if {
        "source_finding",
        "package",
        "target_gate",
        "scope",
        "fix_plan",
        "result",
    } <= keys:
        return "refire_ticket"
    if {"target_gate", "package", "budget", "laps", "final"} <= keys:
        return "simmer_laps"
    if {
        "source_package",
        "strategy_spec",
        "adapter",
        "config_hash",
        "observation",
        "decision_logic",
        "divergence_policy",
        "safety",
        "status",
    } <= keys:
        return "paper_plan"
    if {
        "paper_plan",
        "source_package",
        "data_capture",
        "signals",
        "simulated_orders",
        "quality",
    } <= keys:
        return "observation_manifest"
    if {
        "paper_plan",
        "observation_manifest",
        "sample",
        "comparisons",
        "breaches",
        "decision",
    } <= keys:
        return "divergence_report"
    if {
        "strategy_id",
        "requested_gate",
        "config_hash",
        "adapter",
        "evidence",
        "risk_limits",
        "operations",
        "human_decisions_required",
        "status",
    } <= keys:
        return "approval_pack"
    if {"ledger", "filters", "summary", "packages", "status"} <= keys:
        return "receipt_summary"
    if {
        "gate_id",
        "gate_result",
        "policy_version",
        "policy_hash",
        "package_id",
        "evidence",
        "reviewer",
    } <= keys:
        return "gate_decision"
    if {
        "topic",
        "objective",
        "sources",
        "hypotheses",
        "evidence_gaps",
        "next_tests",
        "status",
    } <= keys:
        return "research_brief"
    if {"target", "reviewer", "findings", "verdict", "evidence", "limitations"} <= keys:
        return "audit_report"
    if {
        "source",
        "venue",
        "asset_class",
        "instrument_id",
        "event_type",
        "event_time_ns",
        "receive_time_ns",
        "ingest_id",
        "payload",
    } <= keys:
        return "canonical_event"
    if {"registry_id", "instruments", "fingerprint"} <= keys:
        return "instrument_registry"
    if {"dataset_id", "checks", "summary", "quarantine", "promotion_impact"} <= keys:
        return "quality_report"
    if {
        "dataset_fingerprint",
        "code_version",
        "config_hash",
        "features",
        "output_fingerprint",
    } <= keys:
        return "feature_manifest"
    if {
        "policy_id",
        "policy_version",
        "asset_class",
        "sizing",
        "limits",
        "stress",
        "policy_hash",
    } <= keys:
        return "risk_policy"
    if {
        "package_id",
        "policy_id",
        "policy_hash",
        "drawdown_distribution",
        "expected_shortfall",
        "scenario_losses",
        "verdict",
    } <= keys:
        return "risk_report"
    if {
        "caller_provider",
        "target_provider",
        "role",
        "objective",
        "workspace_root",
        "mode",
        "timeout_seconds",
        "max_output_bytes",
        "forbidden_actions",
    } <= keys:
        return "agent_task"
    if {
        "task_id",
        "status",
        "summary",
        "findings",
        "changed_paths",
        "next_actions",
        "assumptions",
        "issues",
    } <= keys:
        return "agent_result"
    if {
        "run_id",
        "task_id",
        "task_fingerprint",
        "caller_provider",
        "target_provider",
        "provider",
        "execution",
        "streams",
        "result_fingerprint",
        "patch",
    } <= keys:
        return "agent_run"
    if {
        "owner",
        "trigger",
        "command",
        "inputs",
        "allowed_writes",
        "forbidden_actions",
        "timeout_seconds",
        "retry_policy",
        "alert_sink",
        "freeze_procedure",
    } <= keys:
        return "automation_spec"
    if {
        "automation_spec",
        "idempotency_key",
        "started_at",
        "finished_at",
        "attempts",
        "status",
        "outputs",
        "receipt",
    } <= keys:
        return "automation_run"
    if {
        "severity",
        "detected_at",
        "source",
        "summary",
        "timeline",
        "impact",
        "evidence",
        "actions",
        "status",
    } <= keys:
        return "incident_report"
    if {
        "venue",
        "account_scope",
        "adapter",
        "config_hash",
        "decision",
        "accepted_live_capability_adr",
        "grants_live_approval",
    } <= keys:
        return "human_decision"
    if {
        "before_hash",
        "after_hash",
        "changes",
        "review_required",
        "secrets_present",
    } <= keys:
        return "config_diff"
    if {
        "gateway",
        "config_hash",
        "intent_fingerprint",
        "external_side_effects",
        "transport_available",
        "result",
    } <= keys:
        return "dry_run_proof"
    if {
        "account_equity",
        "micro_notional_cap",
        "daily_loss_cap",
        "max_leverage",
        "freeze_conditions",
        "policy_hash",
    } <= keys:
        return "live_risk_contract"
    return None


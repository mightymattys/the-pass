"""Append-only receipt ledger for The Pass."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .validator import (
    PACKAGE_CORE_ARTIFACTS,
    PACKAGE_OPTIONAL_ARTIFACTS,
    ValidationIssue,
    find_artifact,
    load_document,
    validate_package,
    validate_artifact,
)


LEDGER_SCHEMA_V1 = "the-pass/receipt-ledger-entry/v1"
LEDGER_SCHEMA_V2 = "the-pass/receipt-ledger-entry/v2"
DEFAULT_LEDGER_PATH = Path("experiments/ledger.jsonl")
CORE_GATES = {"research_gate", "paper_gate", "risk_review", "live_gate"}


class LedgerError(Exception):
    """Raised when the receipt ledger cannot be read, verified, or appended."""


@dataclass(frozen=True)
class LedgerAppendResult:
    """Result of appending or finding an existing ledger entry."""

    entry: dict[str, Any]
    appended: bool
    message: str


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_entry(entry: dict[str, Any]) -> str:
    without_hash = {key: value for key, value in entry.items() if key != "entry_hash"}
    return sha256_text(canonical_json(without_hash))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_ledger_entries(ledger_path: Path) -> list[dict[str, Any]]:
    if not ledger_path.exists():
        return []

    entries: list[dict[str, Any]] = []
    with ledger_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                entry = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise LedgerError(f"{ledger_path}:{line_number}: invalid JSON: {exc}") from exc
            if not isinstance(entry, dict):
                raise LedgerError(f"{ledger_path}:{line_number}: ledger entry must be an object")
            entries.append(entry)
    return entries


def verify_ledger_entries(entries: list[dict[str, Any]]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    previous_hash: str | None = None

    for index, entry in enumerate(entries):
        path = f"entry[{index}]"
        schema = entry.get("schema")
        if schema not in {LEDGER_SCHEMA_V1, LEDGER_SCHEMA_V2}:
            issues.append(ValidationIssue(f"{path}.schema", "must be a supported receipt-ledger entry schema"))
        if schema == LEDGER_SCHEMA_V2 and entry.get("entry_kind") not in {"run", "gate_decision"}:
            issues.append(ValidationIssue(f"{path}.entry_kind", "must be run or gate_decision for v2 entries"))

        if entry.get("previous_hash") != previous_hash:
            issues.append(ValidationIssue(f"{path}.previous_hash", "does not match previous entry hash"))

        expected_hash = hash_entry(entry)
        if entry.get("entry_hash") != expected_hash:
            issues.append(ValidationIssue(f"{path}.entry_hash", "does not match entry contents"))

        previous_hash = entry.get("entry_hash") if isinstance(entry.get("entry_hash"), str) else None

    return issues


def verify_ledger_artifacts(
    entries: list[dict[str, Any]],
    ledger_path: Path | None = None,
) -> list[ValidationIssue]:
    """Verify that artifacts referenced by receipts still exist and match their hashes."""

    issues: list[ValidationIssue] = []
    ledger_parent = ledger_path.resolve().parent if ledger_path is not None else Path.cwd().resolve()
    for entry_index, entry in enumerate(entries):
        entry_path = f"entry[{entry_index}]"
        package_value = entry.get("package_path")
        if not isinstance(package_value, str) or not package_value:
            issues.append(ValidationIssue(f"{entry_path}.package_path", "must be a non-empty path"))
            continue

        package_dir = (ledger_parent / package_value).resolve()
        if not package_dir.is_dir():
            issues.append(ValidationIssue(f"{entry_path}.package_path", "package directory does not exist"))
            continue

        artifacts = entry.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            issues.append(ValidationIssue(f"{entry_path}.artifacts", "must contain artifact fingerprints"))
            continue

        for artifact_index, artifact in enumerate(artifacts):
            artifact_path = f"{entry_path}.artifacts[{artifact_index}]"
            if not isinstance(artifact, dict):
                issues.append(ValidationIssue(artifact_path, "must be an object"))
                continue
            relative_value = artifact.get("path")
            expected_hash = artifact.get("sha256")
            if not isinstance(relative_value, str) or not relative_value:
                issues.append(ValidationIssue(f"{artifact_path}.path", "must be a non-empty path"))
                continue
            candidate = (package_dir / relative_value).resolve()
            try:
                candidate.relative_to(package_dir)
            except ValueError:
                issues.append(ValidationIssue(f"{artifact_path}.path", "escapes package directory"))
                continue
            if not candidate.is_file():
                issues.append(ValidationIssue(f"{artifact_path}.path", "referenced artifact does not exist"))
                continue
            if not isinstance(expected_hash, str) or sha256_file(candidate) != expected_hash:
                issues.append(ValidationIssue(f"{artifact_path}.sha256", "does not match artifact contents"))

    return issues


def verify_ledger_file(ledger_path: Path) -> list[ValidationIssue]:
    if not ledger_path.exists():
        return [ValidationIssue(str(ledger_path), "ledger file does not exist")]
    entries = read_ledger_entries(ledger_path)
    return [*verify_ledger_entries(entries), *verify_ledger_artifacts(entries, ledger_path)]


def package_relative_path(package_dir: Path, path: Path) -> str:
    return path.resolve().relative_to(package_dir.resolve()).as_posix()


def artifact_summary(package_dir: Path, artifact_type: str, path: Path) -> dict[str, Any]:
    document = load_document(path)
    artifact_id = document.get("id") if isinstance(document, dict) else None
    return {
        "type": artifact_type,
        "path": package_relative_path(package_dir, path),
        "id": artifact_id if isinstance(artifact_id, str) else "",
        "sha256": sha256_file(path),
    }


def linked_source_notes(package_dir: Path, verdict: dict[str, Any]) -> list[Path]:
    evidence = verdict.get("evidence")
    if not isinstance(evidence, dict):
        return []
    source_notes = evidence.get("source_notes", [])
    if not isinstance(source_notes, list):
        return []

    paths: list[Path] = []
    for value in source_notes:
        if not isinstance(value, str) or not value:
            continue
        candidate = (package_dir / value).resolve()
        try:
            candidate.relative_to(package_dir.resolve())
        except ValueError:
            continue
        if candidate.exists():
            paths.append(candidate)
    return paths


def collect_artifact_summaries(package_dir: Path) -> list[dict[str, Any]]:
    package_dir = package_dir.resolve()
    summaries: list[dict[str, Any]] = []
    seen: set[Path] = set()

    for artifact_type in (*PACKAGE_CORE_ARTIFACTS, *PACKAGE_OPTIONAL_ARTIFACTS):
        path = find_artifact(package_dir, artifact_type)
        if path is None:
            continue
        resolved = path.resolve()
        summaries.append(artifact_summary(package_dir, artifact_type, resolved))
        seen.add(resolved)

    verdict_path = find_artifact(package_dir, "verdict_report")
    if verdict_path is not None:
        verdict = load_document(verdict_path)
        if isinstance(verdict, dict):
            for source_path in linked_source_notes(package_dir, verdict):
                if source_path in seen:
                    continue
                summaries.append(artifact_summary(package_dir, "source_note", source_path))
                seen.add(source_path)

    return sorted(summaries, key=lambda item: (item["type"], item["path"]))


def deterministic_package_id(artifact_summaries: list[dict[str, Any]], run_id: str, strategy_id: str) -> str:
    package_fingerprint = {
        "artifacts": [
            {"path": item["path"], "sha256": item["sha256"], "type": item["type"]}
            for item in artifact_summaries
        ],
        "run_id": run_id,
        "strategy_id": strategy_id,
    }
    return "pkg_" + sha256_text(canonical_json(package_fingerprint))[:24]


def failed_gates(verdict: dict[str, Any]) -> list[str]:
    gate_results = verdict.get("gate_results")
    if not isinstance(gate_results, dict):
        return []
    value = gate_results.get("failed_gates", [])
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def build_run_entry(
    package_dir: Path,
    *,
    recorded_at: str | None = None,
    ledger_path: Path | None = None,
) -> dict[str, Any]:
    package_dir = package_dir.resolve()
    ledger_path = (ledger_path or DEFAULT_LEDGER_PATH).resolve()
    result = validate_package(package_dir)
    if not result.ok:
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in result.issues)
        raise LedgerError(f"cannot add invalid package: {details}")

    strategy_spec_path = find_artifact(package_dir, "strategy_spec")
    run_receipt_path = find_artifact(package_dir, "run_receipt")
    data_manifest_path = find_artifact(package_dir, "data_manifest")
    metrics_report_path = find_artifact(package_dir, "metrics_report")
    cost_waterfall_path = find_artifact(package_dir, "cost_waterfall")
    verdict_report_path = find_artifact(package_dir, "verdict_report")
    if not all(
        (strategy_spec_path, run_receipt_path, data_manifest_path, metrics_report_path, cost_waterfall_path, verdict_report_path)
    ):
        raise LedgerError("validated package unexpectedly missed a core artifact")

    strategy_spec = load_document(strategy_spec_path)  # type: ignore[arg-type]
    run_receipt = load_document(run_receipt_path)  # type: ignore[arg-type]
    verdict = load_document(verdict_report_path)  # type: ignore[arg-type]
    if not isinstance(strategy_spec, dict) or not isinstance(run_receipt, dict) or not isinstance(verdict, dict):
        raise LedgerError("core artifacts must be objects")

    artifact_summaries = collect_artifact_summaries(package_dir)
    strategy_id = str(strategy_spec.get("id", ""))
    run_id = str(run_receipt.get("id", ""))
    package_id = deterministic_package_id(artifact_summaries, run_id=run_id, strategy_id=strategy_id)

    entry = {
        "schema": LEDGER_SCHEMA_V2,
        "entry_kind": "run",
        "recorded_at": recorded_at or utc_now_iso(),
        "package_id": package_id,
        "package_path": Path(os.path.relpath(package_dir, ledger_path.parent)).as_posix(),
        "strategy_id": strategy_id,
        "run_id": run_id,
        "verdict": str(verdict.get("verdict", "")),
        "data_manifest": artifact_summary(package_dir, "data_manifest", data_manifest_path),  # type: ignore[arg-type]
        "metrics_report": artifact_summary(package_dir, "metrics_report", metrics_report_path),  # type: ignore[arg-type]
        "cost_waterfall": artifact_summary(package_dir, "cost_waterfall", cost_waterfall_path),  # type: ignore[arg-type]
        "verdict_report": artifact_summary(package_dir, "verdict_report", verdict_report_path),  # type: ignore[arg-type]
        "source_notes": [
            item for item in artifact_summaries if item["type"] == "source_note"
        ],
        "artifacts": artifact_summaries,
        "open_blockers": failed_gates(verdict),
        "next_action": str(verdict.get("next_action", "")),
        "safety": run_receipt.get("safety", {}),
        "previous_hash": None,
    }
    return entry


def append_ledger_entry(ledger_path: Path, package_dir: Path) -> LedgerAppendResult:
    ledger_path = ledger_path.resolve()
    entries = read_ledger_entries(ledger_path)
    issues = [*verify_ledger_entries(entries), *verify_ledger_artifacts(entries, ledger_path)]
    if issues:
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
        raise LedgerError(f"refusing to append to invalid ledger: {details}")

    entry = build_run_entry(package_dir, ledger_path=ledger_path)
    for existing in entries:
        if existing.get("package_id") == entry["package_id"] and existing.get("entry_kind") == "run":
            return LedgerAppendResult(existing, False, "package already recorded")

    entry["previous_hash"] = entries[-1]["entry_hash"] if entries else None
    entry["entry_hash"] = hash_entry(entry)

    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(canonical_json(entry) + "\n")

    return LedgerAppendResult(entry, True, "receipt appended")


def append_gate_decision(ledger_path: Path, decision_path: Path) -> LedgerAppendResult:
    ledger_path = ledger_path.resolve()
    decision_path = decision_path.resolve()
    entries = read_ledger_entries(ledger_path)
    issues = [*verify_ledger_entries(entries), *verify_ledger_artifacts(entries, ledger_path)]
    if issues:
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in issues)
        raise LedgerError(f"refusing to append to invalid ledger: {details}")

    validation = validate_artifact(decision_path, artifact_type="gate_decision")
    if not validation.ok:
        details = "; ".join(f"{issue.path}: {issue.message}" for issue in validation.issues)
        raise LedgerError(f"cannot add invalid gate decision: {details}")
    decision = load_document(decision_path)
    if not isinstance(decision, dict):
        raise LedgerError("gate decision must be an object")
    if decision.get("gate_id") not in CORE_GATES:
        raise LedgerError("gate decision uses a non-canonical gate")

    package_value = decision.get("package_path")
    if not isinstance(package_value, str) or not package_value:
        raise LedgerError("gate decision package_path must be non-empty")
    package_dir = (decision_path.parent / package_value).resolve()
    try:
        decision_path.relative_to(package_dir)
    except ValueError as exc:
        raise LedgerError("gate decision must be stored inside its package directory") from exc

    run_entry = build_run_entry(package_dir, ledger_path=ledger_path)
    if decision.get("package_id") != run_entry["package_id"]:
        raise LedgerError("gate decision package_id does not match current package artifacts")
    if not any(
        entry.get("entry_kind") == "run" and entry.get("package_id") == run_entry["package_id"]
        for entry in entries
    ):
        raise LedgerError("gate decision requires the exact run package to be recorded first")

    evidence = decision.get("evidence", [])
    if not isinstance(evidence, list) or not evidence:
        raise LedgerError("gate decision must contain evidence fingerprints")
    for item in evidence:
        if not isinstance(item, dict):
            raise LedgerError("gate decision evidence rows must be objects")
        evidence_path = (package_dir / str(item.get("path", ""))).resolve()
        try:
            evidence_path.relative_to(package_dir)
        except ValueError as exc:
            raise LedgerError("gate decision evidence escapes package directory") from exc
        if not evidence_path.is_file() or sha256_file(evidence_path) != item.get("sha256"):
            raise LedgerError(f"gate decision evidence fingerprint mismatch: {item.get('path', '')}")

    artifacts = [*evidence, artifact_summary(package_dir, "gate_decision", decision_path)]
    entry = {
        "schema": LEDGER_SCHEMA_V2,
        "entry_kind": "gate_decision",
        "recorded_at": utc_now_iso(),
        "decision_id": decision["id"],
        "package_id": decision["package_id"],
        "package_path": Path(os.path.relpath(package_dir, ledger_path.parent)).as_posix(),
        "strategy_id": run_entry["strategy_id"],
        "run_id": run_entry["run_id"],
        "gate": decision["gate_id"],
        "gate_result": decision["gate_result"],
        "policy_version": decision["policy_version"],
        "policy_hash": decision["policy_hash"],
        "reviewer": decision["reviewer"],
        "verdict": run_entry["verdict"],
        "artifacts": artifacts,
        "open_blockers": decision["blockers"],
        "next_action": decision["summary"],
        "safety": decision["safety"],
        "previous_hash": None,
    }

    for existing in entries:
        if (
            existing.get("entry_kind") == "gate_decision"
            and existing.get("decision_id") == entry["decision_id"]
        ):
            return LedgerAppendResult(existing, False, "gate decision already recorded")

    entry["previous_hash"] = entries[-1]["entry_hash"] if entries else None
    entry["entry_hash"] = hash_entry(entry)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_path.open("a", encoding="utf-8") as handle:
        handle.write(canonical_json(entry) + "\n")
    return LedgerAppendResult(entry, True, "gate decision appended")


def has_passed_gate(entries: list[dict[str, Any]], package_id: str, gate: str) -> bool:
    return any(
        entry.get("schema") == LEDGER_SCHEMA_V2
        and entry.get("entry_kind") == "gate_decision"
        and entry.get("package_id") == package_id
        and entry.get("gate") == gate
        and entry.get("gate_result") == "pass"
        for entry in entries
    )


def ledger_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "entries": len(entries),
        "packages": [
            {
                "package_id": entry.get("package_id", ""),
                "entry_kind": entry.get("entry_kind", "legacy"),
                "strategy_id": entry.get("strategy_id", ""),
                "run_id": entry.get("run_id", ""),
                "gate": entry.get("gate", ""),
                "gate_result": entry.get("gate_result", ""),
                "verdict": entry.get("verdict", ""),
                "package_path": entry.get("package_path", ""),
                "data_manifest": (entry.get("data_manifest") or {}).get("path", ""),
                "cost_waterfall": (entry.get("cost_waterfall") or {}).get("path", ""),
                "open_blockers": entry.get("open_blockers", []),
                "entry_hash": entry.get("entry_hash", ""),
            }
            for entry in entries
        ],
    }


def format_ledger_summary(ledger_path: Path, entries: list[dict[str, Any]]) -> str:
    if not entries:
        return f"No receipts recorded in {ledger_path}"

    lines = [f"Ledger: {ledger_path}", f"Entries: {len(entries)}"]
    for entry in entries:
        blockers = entry.get("open_blockers", [])
        blocker_text = ", ".join(blockers) if isinstance(blockers, list) and blockers else "none"
        lines.extend(
            [
                "",
                f"- {entry.get('package_id', '')} | {entry.get('entry_kind', 'legacy')} | "
                f"{entry.get('gate', '')} | {entry.get('gate_result', '') or entry.get('verdict', '')}",
                f"  strategy: {entry.get('strategy_id', '')}",
                f"  run: {entry.get('run_id', '')}",
                f"  package: {entry.get('package_path', '')}",
                f"  data: {(entry.get('data_manifest') or {}).get('path', '')}",
                f"  cost: {(entry.get('cost_waterfall') or {}).get('path', '')}",
                f"  blockers: {blocker_text}",
            ]
        )
    return "\n".join(lines)

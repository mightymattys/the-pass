"""Domain handlers for whitelisted scheduler-neutral automation jobs."""

from __future__ import annotations

import argparse
import glob
import json
from pathlib import Path
from typing import Any

import yaml

from the_pass.data.contracts import stable_fingerprint
from the_pass.roadmap import load_roadmap, validate_roadmap_document
from the_pass.validator import validate_package

from .runner import AUTOMATION_COMMANDS


def _resolve(root: Path, value: str) -> Path:
    path = (root / value).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("automation input path escapes workspace") from exc
    return path


def _json(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"automation input must be an object: {path}")
    return document


def _glob(root: Path, pattern: str) -> list[Path]:
    if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
        raise ValueError("automation glob must stay inside workspace")
    paths = []
    for value in glob.glob(str(root / pattern), recursive=True):
        path = Path(value).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ValueError("automation glob escaped workspace") from exc
        if path.is_file() and not path.is_symlink():
            paths.append(path)
    return sorted(set(paths))


def _data_health(root: Path, inputs: dict[str, Any]) -> dict[str, Any]:
    paths = _glob(root, str(inputs.get("quality_reports", "")))
    reports = []
    for path in paths:
        try:
            document = _json(path)
        except (json.JSONDecodeError, UnicodeError):
            continue
        if document.get("schema_version") == 2 and "promotion_impact" in document:
            reports.append((path, document))
    if not reports:
        raise ValueError("data_health found no QualityReport evidence")
    blocked = [str(path.relative_to(root)) for path, row in reports if row["promotion_impact"] == "blocked"]
    if blocked:
        raise ValueError(f"data_health found blocking reports: {', '.join(blocked)}")
    return {
        "reports_checked": len(reports),
        "report_fingerprints": {
            str(path.relative_to(root)): stable_fingerprint(row) for path, row in reports
        },
    }


def _corpus(root: Path, inputs: dict[str, Any]) -> dict[str, Any]:
    registry = _resolve(root, str(inputs.get("registry", inputs.get("sources", ""))))
    document = yaml.safe_load(registry.read_text(encoding="utf-8"))
    sources = document.get("sources") if isinstance(document, dict) else None
    if not isinstance(sources, list) or not sources:
        raise ValueError("research registry has no sources")
    missing = [row.get("path") for row in sources if not _resolve(root, str(row.get("path", ""))).is_file()]
    if missing:
        raise ValueError("research registry references missing source notes")
    return {
        "sources_checked": len(sources),
        "reviewed": sum(row.get("status") == "reviewed" for row in sources),
        "registry_fingerprint": stable_fingerprint(registry.read_text(encoding="utf-8")),
    }


def _nightly_baselines(root: Path, inputs: dict[str, Any]) -> dict[str, Any]:
    if inputs.get("suite") != "b2-public-baselines":
        raise ValueError("nightly_baselines requires the registered b2-public-baselines suite")
    packages = sorted((root / "examples" / "b2-baselines").glob("*/package"))
    if not packages:
        raise ValueError("nightly_baselines found no baseline packages")
    invalid = [str(path.relative_to(root)) for path in packages if not validate_package(path).ok]
    if invalid:
        raise ValueError(f"nightly_baselines found invalid packages: {', '.join(invalid)}")
    return {
        "packages_checked": len(packages),
        "package_receipts": {
            str(path.relative_to(root)): stable_fingerprint(
                _json(path / "run_receipt.json")
            )
            for path in packages
        },
    }


def _gate_checker(root: Path, inputs: dict[str, Any]) -> dict[str, Any]:
    path = _resolve(root, str(inputs.get("roadmap", "")))
    document = load_roadmap(path)
    validate_roadmap_document(document, root=root)
    return {
        "roadmap_fingerprint": stable_fingerprint(path.read_text(encoding="utf-8")),
        "milestones_checked": len(document["milestones"]),
        "gate_state_changed": False,
    }


def _risk_monitor(root: Path, inputs: dict[str, Any]) -> dict[str, Any]:
    path = _resolve(root, str(inputs.get("policy", "")))
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not document.get("asset_classes"):
        raise ValueError("risk_monitor policy is invalid")
    return {
        "policy_version": document.get("policy_version"),
        "policy_fingerprint": stable_fingerprint(path.read_text(encoding="utf-8")),
        "asset_classes_checked": sorted(document["asset_classes"]),
        "breaches": [],
    }


def _paper_reports(root: Path, inputs: dict[str, Any], *, command: str) -> dict[str, Any]:
    paper_root = _resolve(root, str(inputs.get("paper_root", inputs.get("observation_dir", ""))))
    if not paper_root.is_dir():
        raise ValueError(f"{command} paper root does not exist")
    documents = []
    for path in sorted(paper_root.rglob("*.json")):
        try:
            documents.append((path, _json(path)))
        except (json.JSONDecodeError, UnicodeError, ValueError):
            continue
    if not documents:
        raise ValueError(f"{command} found no paper evidence")
    if command == "paper_observer":
        observations = [row for _path, row in documents if "paper_gate_eligible" in row]
        if not observations:
            raise ValueError("paper_observer found no resumable observation state")
        if any(row.get("status") == "frozen" for row in observations):
            raise ValueError("paper_observer found a frozen observation")
    elif command == "drift_report":
        if not any("signals" in row and "fills" in row for _path, row in documents):
            raise ValueError("drift_report found no signal/fill evidence")
    elif command == "tca_report":
        if not any("costs" in row and "fills" in row for _path, row in documents):
            raise ValueError("tca_report found no fill cost evidence")
    return {
        "documents_checked": len(documents),
        "evidence_fingerprints": {
            str(path.relative_to(root)): stable_fingerprint(row) for path, row in documents
        },
    }


def execute_handler(command: str, inputs: dict[str, Any], *, root: Path) -> dict[str, Any]:
    if command == "data_health":
        return _data_health(root, inputs)
    if command == "corpus_refresh":
        return _corpus(root, inputs)
    if command == "nightly_baselines":
        return _nightly_baselines(root, inputs)
    if command == "gate_checker":
        return _gate_checker(root, inputs)
    if command in {"paper_observer", "drift_report", "tca_report"}:
        return _paper_reports(root, inputs, command=command)
    if command == "risk_monitor":
        return _risk_monitor(root, inputs)
    if command == "weekly_research_summary":
        corpus = _corpus(root, inputs)
        experiments = _resolve(root, str(inputs.get("experiments", "")))
        packages = list(experiments.glob("*/package/run_receipt.json"))
        if not packages:
            raise ValueError("weekly_research_summary found no experiment receipts")
        return {**corpus, "experiments_checked": len(packages)}
    raise ValueError(f"automation handler is not implemented: {command}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--command", choices=AUTOMATION_COMMANDS, required=True)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--attempt", type=int, required=True)
    args = parser.parse_args()
    inputs = json.loads(args.inputs.read_text(encoding="utf-8"))
    if not isinstance(inputs, dict):
        raise ValueError("automation inputs must be an object")
    findings = execute_handler(args.command, inputs, root=Path.cwd().resolve())
    args.output_dir.mkdir(parents=True, exist_ok=True)
    output = args.output_dir / f"{args.command}-snapshot.json"
    output.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "command": args.command,
                "inputs_fingerprint": stable_fingerprint(inputs),
                "attempt": args.attempt,
                "status": "complete",
                "read_only_external_boundary": True,
                "findings": findings,
                "findings_fingerprint": stable_fingerprint(findings),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "worker-result.json").write_text(
        json.dumps({"outputs": [output.name], "status": "complete"}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

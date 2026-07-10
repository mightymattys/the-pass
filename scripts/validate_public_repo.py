#!/usr/bin/env python3
"""Validate the public-safe The Pass repository scaffold."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from the_pass.validator import ARTIFACT_SCHEMAS, ARTIFACT_TYPES, validate_artifact, validate_package  # noqa: E402

PLACEHOLDER_MARKER = "[" + "TO" + "DO:"

FORBIDDEN_PATTERNS = [
    re.compile(r"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"ghp_[A-Za-z0-9_]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"xox[baprs]-[A-Za-z0-9-]{20,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]
LIVE_ORDER_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bcreate_order\b",
        r"\bplace_order\b",
        r"\bsend_order\b",
        r"\bsubmit_order\b",
        r"\bmarket_order\b",
        r"\blimit_order\b",
        r"\border_send\b",
        r"\border_create\b",
        r"\bccxt\b",
        r"\bib_insync\b",
        r"\bpy_clob_client\b",
        r"\balpaca_trade_api\b",
    )
]
LIVE_SCAN_DIRS = {"src", "scripts", ".github", ".codex-plugin"}
LIVE_SCAN_SUFFIXES = {".py", ".toml", ".yaml", ".yml", ".json"}
PAID_OR_PRIVATE_DATA_SUFFIXES = {".parquet", ".feather", ".h5", ".hdf5", ".duckdb", ".sqlite", ".db", ".pkl", ".pickle"}
ALLOWED_DATA_DIR_FILES = {"README.md", ".gitkeep"}

IGNORED_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".venv",
    "venv",
}
MARKDOWN_LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
EXAMPLE_PACKAGES = {
    "synthetic-breakout": {"verdict": "blocked", "adapter_mode": "diagnostic"},
    "synthetic-random-baseline": {"verdict": "kill", "adapter_mode": "diagnostic"},
}
REQUIRED_TEMPLATES = {f"{artifact_type}.yaml" for artifact_type in ARTIFACT_TYPES}
REQUIRED_WORKFLOW_DIR_READMES = {
    "experiments/screens/README.md",
    "experiments/runs/README.md",
    "experiments/paper/README.md",
    "research/hypotheses/README.md",
    "reports/reviews/README.md",
    "reports/screens/README.md",
    "reports/paper/README.md",
    "reports/approval_packs/README.md",
    "reports/receipt_summaries/README.md",
    "reports/simmer/README.md",
}
SKILL_EXIT_STATES = {
    "mise": ("ready", "repaired", "blocked"),
    "research": ("reviewed", "rejected", "blocked"),
    "spec": ("draft", "research_ready", "blocked"),
    "screen": ("reject", "revise", "backtest_candidate", "blocked"),
    "backtest": ("complete", "blocked"),
    "taste": ("paper_candidate", "blocked", "revise", "kill"),
    "refire": ("fixed", "still_blocked"),
    "simmer": ("passed", "blocked", "killed"),
    "paper": ("paper_ready", "blocked"),
    "plate": ("packaged", "blocked"),
    "receipts": ("summarized", "blocked"),
}
REQUIRED_SKILL_SECTIONS = (
    "Inputs",
    "Read First",
    "Editable Paths",
    "Blocked Paths",
    "Procedure",
    "Required Checks",
    "Outputs",
    "Exit States",
)


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def iter_files() -> list[Path]:
    try:
        result = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=ROOT,
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError):
        candidates = ROOT.rglob("*")
    else:
        candidates = (ROOT / relative for relative in result.stdout.decode("utf-8").split("\0") if relative)

    files: list[Path] = []
    for path in candidates:
        if any(part in IGNORED_DIRS for part in path.parts):
            continue
        if any(part.endswith(".egg-info") for part in path.parts):
            continue
        if path.is_file():
            files.append(path)
    return files


def validate_json(path: Path) -> None:
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {path.relative_to(ROOT)}: {exc}")


def validate_yaml(path: Path) -> None:
    try:
        yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        fail(f"invalid YAML in {path.relative_to(ROOT)}: {exc}")


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fail_validation_result(label: str, result) -> None:
    if result.ok:
        return
    details = "; ".join(f"{issue.path}: {issue.message}" for issue in result.issues)
    fail(f"{label} validation failed: {details}")


def validate_plugin_manifest() -> None:
    manifest_path = ROOT / ".codex-plugin" / "plugin.json"
    if not manifest_path.exists():
        fail("missing .codex-plugin/plugin.json")
    validate_json(manifest_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("name") != "the-pass":
        fail("plugin name must be the-pass")
    if manifest.get("skills") != "./skills/":
        fail("plugin must point skills to ./skills/")
    interface = manifest.get("interface") or {}
    for field in ("displayName", "shortDescription", "longDescription", "developerName", "category"):
        if not interface.get(field):
            fail(f"plugin interface missing {field}")


def validate_python_package() -> None:
    pyproject_path = ROOT / "pyproject.toml"
    if not pyproject_path.exists():
        fail("missing pyproject.toml")
    cli_path = ROOT / "src" / "the_pass" / "cli.py"
    validator_path = ROOT / "src" / "the_pass" / "validator.py"
    ledger_path = ROOT / "src" / "the_pass" / "ledger.py"
    adapter_contract_path = ROOT / "src" / "the_pass" / "adapter_contract.py"
    if not cli_path.exists():
        fail("missing src/the_pass/cli.py")
    if not validator_path.exists():
        fail("missing src/the_pass/validator.py")
    if not ledger_path.exists():
        fail("missing src/the_pass/ledger.py")
    if not adapter_contract_path.exists():
        fail("missing src/the_pass/adapter_contract.py")


def validate_skills() -> None:
    skills_dir = ROOT / "skills"
    expected = set(SKILL_EXIT_STATES)
    present = {path.name for path in skills_dir.iterdir() if path.is_dir()}
    missing = expected - present
    if missing:
        fail(f"missing skills: {', '.join(sorted(missing))}")
    unexpected = present - expected
    if unexpected:
        fail(f"skills without registered command contracts: {', '.join(sorted(unexpected))}")
    for name in sorted(expected):
        skill_path = skills_dir / name / "SKILL.md"
        if not skill_path.exists():
            fail(f"missing {skill_path.relative_to(ROOT)}")
        text = skill_path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            fail(f"{skill_path.relative_to(ROOT)} missing front matter")
        parts = text.split("---", 2)
        if len(parts) != 3:
            fail(f"{skill_path.relative_to(ROOT)} has malformed front matter")
        try:
            front_matter = yaml.safe_load(parts[1])
        except yaml.YAMLError as exc:
            fail(f"{skill_path.relative_to(ROOT)} has invalid front matter: {exc}")
        if not isinstance(front_matter, dict):
            fail(f"{skill_path.relative_to(ROOT)} front matter must be an object")
        if front_matter.get("name") != name:
            fail(f"{skill_path.relative_to(ROOT)} has wrong skill name")
        if set(front_matter) != {"name", "description"}:
            fail(f"{skill_path.relative_to(ROOT)} front matter may contain only name and description")
        description = front_matter.get("description")
        if not isinstance(description, str) or not description.strip():
            fail(f"{skill_path.relative_to(ROOT)} has no skill description")
        for section in REQUIRED_SKILL_SECTIONS:
            if f"## {section}\n" not in text:
                fail(f"{skill_path.relative_to(ROOT)} missing section: {section}")
        for artifact_type in re.findall(r"--type ([a-z_]+)", text):
            if artifact_type not in ARTIFACT_TYPES:
                fail(f"{skill_path.relative_to(ROOT)} references unknown artifact type: {artifact_type}")
        for reference in re.findall(r"`((?:docs|schemas|templates)/[^`]+)`", text):
            if not (ROOT / reference).exists():
                fail(f"{skill_path.relative_to(ROOT)} references missing path: {reference}")
        exit_section = text.split("## Exit States\n", 1)[1]
        exit_states = tuple(re.findall(r"^- `([^`]+)`:", exit_section, flags=re.MULTILINE))
        if exit_states != SKILL_EXIT_STATES[name]:
            fail(
                f"{skill_path.relative_to(ROOT)} exit states {exit_states} do not match "
                f"{SKILL_EXIT_STATES[name]}"
            )

    command_docs = (ROOT / "docs" / "plugin" / "COMMANDS.md").read_text(encoding="utf-8")
    documented: dict[str, tuple[str, ...]] = {}
    for line in command_docs.splitlines():
        match = re.match(r"\| `/the-pass:([a-z-]+)(?: [^`]*)?` \|", line)
        if match is None:
            continue
        cells = [cell.strip() for cell in line.split("|")]
        documented[match.group(1)] = tuple(state.strip() for state in cells[4].split(","))
    if documented != SKILL_EXIT_STATES:
        fail("docs/plugin/COMMANDS.md exit states do not match skill contracts")


def validate_schemas() -> None:
    required = {
        schema_name
        for versions in ARTIFACT_SCHEMAS.values()
        for schema_name in versions.values()
    }
    schemas_dir = ROOT / "schemas"
    present = {path.name for path in schemas_dir.glob("*.json")}
    missing = required - present
    if missing:
        fail(f"missing schemas: {', '.join(sorted(missing))}")
    unexpected = present - required
    if unexpected:
        fail(f"schemas without registered artifact types: {', '.join(sorted(unexpected))}")
    for path in schemas_dir.glob("*.json"):
        validate_json(path)
        schema = json.loads(path.read_text(encoding="utf-8"))
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            fail(f"invalid JSON Schema in {path.relative_to(ROOT)}: {exc.message}")

        packaged_path = ROOT / "src" / "the_pass" / "schemas" / path.name
        if not packaged_path.exists():
            fail(f"missing packaged schema: {packaged_path.relative_to(ROOT)}")
        if path.read_bytes() != packaged_path.read_bytes():
            fail(f"packaged schema differs from root schema: {path.name}")

    packaged_present = {path.name for path in (ROOT / "src" / "the_pass" / "schemas").glob("*.json")}
    stale_packaged = packaged_present - present
    if stale_packaged:
        fail(f"packaged schemas without root counterparts: {', '.join(sorted(stale_packaged))}")


def validate_templates() -> None:
    templates_dir = ROOT / "templates"
    present = {path.name for path in templates_dir.glob("*.yaml")}
    missing = REQUIRED_TEMPLATES - present
    if missing:
        fail(f"missing templates: {', '.join(sorted(missing))}")
    unexpected = present - REQUIRED_TEMPLATES
    if unexpected:
        fail(f"templates without registered artifact types: {', '.join(sorted(unexpected))}")
    for name in sorted(REQUIRED_TEMPLATES):
        validate_yaml(templates_dir / name)
        artifact_type = Path(name).stem
        if artifact_type not in ARTIFACT_TYPES:
            fail(f"template has no registered artifact type: {name}")
        document = yaml.safe_load((templates_dir / name).read_text(encoding="utf-8"))
        expected_version = max(ARTIFACT_SCHEMAS[artifact_type])
        if not isinstance(document, dict) or document.get("schema_version") != expected_version:
            fail(f"template {name} must use latest schema_version {expected_version}")


def validate_packaged_policy() -> None:
    root_policy = ROOT / "config" / "gate-policies.v1.yaml"
    packaged_policy = ROOT / "src" / "the_pass" / "policies" / "gate-policies.v1.yaml"
    if not root_policy.is_file() or not packaged_policy.is_file():
        fail("gate policy must exist in config and packaged policy directories")
    validate_yaml(root_policy)
    validate_yaml(packaged_policy)
    if root_policy.read_bytes() != packaged_policy.read_bytes():
        fail("packaged gate policy differs from config/gate-policies.v1.yaml")
    root_risk_policy = ROOT / "config" / "risk-policies.v1.yaml"
    packaged_risk_policy = ROOT / "src" / "the_pass" / "policies" / "risk-policies.v1.yaml"
    if not root_risk_policy.is_file() or not packaged_risk_policy.is_file():
        fail("risk policy must exist in config and packaged policy directories")
    validate_yaml(root_risk_policy)
    validate_yaml(packaged_risk_policy)
    if root_risk_policy.read_bytes() != packaged_risk_policy.read_bytes():
        fail("packaged risk policy differs from config/risk-policies.v1.yaml")


def validate_workflow_directories() -> None:
    for relative in sorted(REQUIRED_WORKFLOW_DIR_READMES):
        if not (ROOT / relative).exists():
            fail(f"missing workflow directory README: {relative}")


def validate_adapter_examples() -> None:
    adapters_dir = ROOT / "examples" / "adapters"
    required = {
        "dummy-diagnostic.yaml",
        "crypto-binance-spot-klines.yaml",
        "generic-futures-contract.yaml",
        "generic-prediction-market.yaml",
        "crypto-binance-spot-klines-source-note.json",
    }
    if not adapters_dir.exists():
        fail("missing examples/adapters")
    present = {path.name for path in adapters_dir.iterdir() if path.is_file()}
    missing = required - present
    if missing:
        fail(f"missing adapter examples: {', '.join(sorted(missing))}")
    validate_json(adapters_dir / "crypto-binance-spot-klines-source-note.json")
    for name in (
        "dummy-diagnostic.yaml",
        "crypto-binance-spot-klines.yaml",
        "generic-futures-contract.yaml",
        "generic-prediction-market.yaml",
    ):
        fail_validation_result(
            f"examples/adapters/{name}",
            validate_artifact(adapters_dir / name, artifact_type="adapter"),
        )
    fail_validation_result(
        "examples/adapters/crypto-binance-spot-klines-source-note.json",
        validate_artifact(adapters_dir / "crypto-binance-spot-klines-source-note.json", artifact_type="source_note"),
    )


def validate_example_packages() -> None:
    required = {
        "adapter.json",
        "source_note.json",
        "strategy_spec.json",
        "data_manifest.json",
        "run_receipt.json",
        "metrics_report.json",
        "cost_waterfall.json",
        "verdict_report.json",
    }
    for example_name, expected in EXAMPLE_PACKAGES.items():
        package_dir = ROOT / "examples" / example_name / "package"
        if not package_dir.exists():
            fail(f"missing examples/{example_name}/package")
        present = {path.name for path in package_dir.glob("*.json")}
        missing = required - present
        if missing:
            fail(f"{example_name} example missing artifacts: {', '.join(sorted(missing))}")
        for name in sorted(required):
            validate_json(package_dir / name)

        adapter = json.loads((package_dir / "adapter.json").read_text(encoding="utf-8"))
        if adapter.get("mode") != expected["adapter_mode"]:
            fail(f"{example_name} adapter must stay {expected['adapter_mode']}")
        adapter_safety = adapter.get("safety") or {}
        for field in ("live_trading_enabled", "real_order_path_available", "credentials_required"):
            if adapter_safety.get(field) is not False:
                fail(f"{example_name} adapter safety.{field} must be false")

        receipt = json.loads((package_dir / "run_receipt.json").read_text(encoding="utf-8"))
        receipt_safety = receipt.get("safety") or {}
        for field in ("live_trading_enabled", "real_order_path_available", "credentials_available"):
            if receipt_safety.get(field) is not False:
                fail(f"{example_name} run receipt safety.{field} must be false")

        manifest = json.loads((package_dir / "data_manifest.json").read_text(encoding="utf-8"))
        source = manifest.get("source") or {}
        raw_path = source.get("raw_path")
        if raw_path:
            data_path = (package_dir / raw_path).resolve()
            try:
                data_path.relative_to(ROOT)
            except ValueError:
                fail(f"{example_name} raw data path escapes repo")
            if not data_path.exists():
                fail(f"{example_name} raw data path is missing: {raw_path}")
            fingerprint = manifest.get("fingerprint") or {}
            if fingerprint.get("method") == "sha256" and fingerprint.get("value") != sha256_file(data_path):
                fail(f"{example_name} data fingerprint does not match {raw_path}")

        verdict = json.loads((package_dir / "verdict_report.json").read_text(encoding="utf-8"))
        if verdict.get("verdict") != expected["verdict"]:
            fail(f"{example_name} verdict must stay {expected['verdict']}")
        if expected["verdict"] == "kill" and not verdict.get("kill_reason"):
            fail(f"{example_name} killed example must keep kill_reason")
        fail_validation_result(f"examples/{example_name}/package", validate_package(package_dir))


def validate_markdown_links() -> None:
    for path in iter_files():
        if path.suffix.lower() != ".md":
            continue
        text = path.read_text(encoding="utf-8")
        for match in MARKDOWN_LINK.finditer(text):
            target = match.group(1).strip()
            if not target or target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            target_path = target.split("#", 1)[0]
            if not target_path:
                continue
            resolved = (path.parent / target_path).resolve()
            try:
                resolved.relative_to(ROOT)
            except ValueError:
                fail(f"markdown link escapes repo in {path.relative_to(ROOT)}: {target}")
            if not resolved.exists():
                fail(f"broken markdown link in {path.relative_to(ROOT)}: {target}")


def validate_public_safety() -> None:
    for path in iter_files():
        if path.stat().st_size > 1_000_000:
            fail(f"unexpected large tracked-style file: {path.relative_to(ROOT)}")
        if path.suffix.lower() in PAID_OR_PRIVATE_DATA_SUFFIXES:
            fail(f"paid/private data-like file extension in tracked path: {path.relative_to(ROOT)}")
        if "data" in path.parts:
            data_index = path.parts.index("data")
            if len(path.parts) > data_index + 1 and path.parts[data_index + 1] in {"raw", "normalized"}:
                if path.name not in ALLOWED_DATA_DIR_FILES:
                    fail(f"tracked data file is not allowed in {path.relative_to(ROOT)}")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if PLACEHOLDER_MARKER in text:
            fail(f"leftover scaffold placeholder in {path.relative_to(ROOT)}")
        for pattern in FORBIDDEN_PATTERNS:
            if pattern.search(text):
                fail(f"secret-like pattern in {path.relative_to(ROOT)}")


def validate_no_live_order_paths() -> None:
    for path in iter_files():
        if path.suffix.lower() not in LIVE_SCAN_SUFFIXES:
            continue
        top_level = path.relative_to(ROOT).parts[0]
        if top_level not in LIVE_SCAN_DIRS:
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in LIVE_ORDER_PATTERNS:
            if pattern.search(text):
                fail(f"live order-placement pattern in {path.relative_to(ROOT)}: {pattern.pattern}")


def main() -> int:
    for path in iter_files():
        if path.suffix == ".json":
            validate_json(path)
    validate_plugin_manifest()
    validate_python_package()
    validate_skills()
    validate_schemas()
    validate_templates()
    validate_packaged_policy()
    validate_workflow_directories()
    validate_adapter_examples()
    validate_example_packages()
    validate_markdown_links()
    validate_public_safety()
    validate_no_live_order_paths()
    subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_roadmap.py")], cwd=ROOT, check=True)
    subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_research_corpus.py")], cwd=ROOT, check=True)
    subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_data_foundation.py")], cwd=ROOT, check=True)
    subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_b2_harness.py")], cwd=ROOT, check=True)
    subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_v3_audit.py")], cwd=ROOT, check=True)
    subprocess.run([sys.executable, str(ROOT / "scripts" / "validate_p4_framework.py")], cwd=ROOT, check=True)
    print("public repo validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

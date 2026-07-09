#!/usr/bin/env python3
"""Validate the public-safe The Pass repository scaffold."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError


ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER_MARKER = "[" + "TO" + "DO:"

FORBIDDEN_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
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


def fail(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def iter_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
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


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
    expected = {
        "mise",
        "research",
        "spec",
        "screen",
        "backtest",
        "taste",
        "refire",
        "simmer",
        "paper",
        "plate",
        "receipts",
    }
    present = {path.name for path in skills_dir.iterdir() if path.is_dir()}
    missing = expected - present
    if missing:
        fail(f"missing skills: {', '.join(sorted(missing))}")
    for name in sorted(expected):
        skill_path = skills_dir / name / "SKILL.md"
        if not skill_path.exists():
            fail(f"missing {skill_path.relative_to(ROOT)}")
        text = skill_path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            fail(f"{skill_path.relative_to(ROOT)} missing front matter")
        if f'name: "the-pass:{name}"' not in text and f"name: the-pass:{name}" not in text:
            fail(f"{skill_path.relative_to(ROOT)} has wrong skill name")


def validate_schemas() -> None:
    required = {
        "adapter.schema.json",
        "source_note.schema.json",
        "strategy_spec.schema.json",
        "data_manifest.schema.json",
        "run_receipt.schema.json",
        "metrics_report.schema.json",
        "cost_waterfall.schema.json",
        "verdict_report.schema.json",
    }
    schemas_dir = ROOT / "schemas"
    present = {path.name for path in schemas_dir.glob("*.json")}
    missing = required - present
    if missing:
        fail(f"missing schemas: {', '.join(sorted(missing))}")
    for path in schemas_dir.glob("*.json"):
        validate_json(path)
        schema = json.loads(path.read_text(encoding="utf-8"))
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            fail(f"invalid JSON Schema in {path.relative_to(ROOT)}: {exc.message}")


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
    validate_adapter_examples()
    validate_example_packages()
    validate_markdown_links()
    validate_public_safety()
    validate_no_live_order_paths()
    print("public repo validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Command line interface for The Pass."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .ledger import (
    DEFAULT_LEDGER_PATH,
    LedgerError,
    append_ledger_entry,
    format_ledger_summary,
    ledger_summary,
    read_ledger_entries,
    verify_ledger_file,
)
from .validator import ARTIFACT_TYPES, ValidationResult, validate_artifact, validate_package


def print_result(result: ValidationResult, *, output_format: str, success_message: str) -> None:
    if output_format == "json":
        print(json.dumps(result.as_dict(), indent=2, sort_keys=True))
        return

    if result.ok:
        print(success_message)
        return

    print("validation failed", file=sys.stderr)
    for issue in result.issues:
        print(f"- {issue.path}: {issue.message}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="the-pass", description="Validate The Pass artifacts and packages.")
    parser.add_argument("--version", action="version", version=f"the-pass {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="Validate one artifact.")
    validate_parser.add_argument("artifact", type=Path, help="Artifact path, JSON or YAML.")
    validate_parser.add_argument(
        "--type",
        choices=sorted(ARTIFACT_TYPES),
        help="Artifact type. If omitted, inferred from filename or fields.",
    )
    validate_parser.add_argument("--schema-dir", type=Path, help="Override schema directory.")
    validate_parser.add_argument("--format", choices=("text", "json"), default="text", help="Output format.")

    package_parser = subparsers.add_parser("validate-package", help="Validate a run package directory.")
    package_parser.add_argument("package", type=Path, help="Package directory.")
    package_parser.add_argument("--schema-dir", type=Path, help="Override schema directory.")
    package_parser.add_argument("--format", choices=("text", "json"), default="text", help="Output format.")

    receipts_parser = subparsers.add_parser("receipts", help="Summarize or update the append-only receipt ledger.")
    receipts_parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER_PATH, help="Ledger JSONL path.")
    receipts_parser.add_argument("--format", choices=("text", "json"), default="text", help="Output format.")
    receipts_subparsers = receipts_parser.add_subparsers(dest="receipts_command")

    receipts_add = receipts_subparsers.add_parser("add", help="Validate a package and append its receipt.")
    receipts_add.add_argument("package", type=Path, help="Package directory.")
    receipts_add.add_argument("--gate", default="research_gate", help="Gate name recorded in the ledger.")
    receipts_add.add_argument("--ledger", dest="sub_ledger", type=Path, help="Ledger JSONL path.")

    receipts_verify = receipts_subparsers.add_parser("verify", help="Verify the ledger hash chain.")
    receipts_verify.add_argument("--ledger", dest="sub_ledger", type=Path, help="Ledger JSONL path.")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "validate":
        result = validate_artifact(args.artifact, schema_dir=args.schema_dir, artifact_type=args.type)
        artifact_type = result.artifact_type or "artifact"
        print_result(
            result,
            output_format=args.format,
            success_message=f"{args.artifact} validates as {artifact_type}",
        )
        return 0 if result.ok else 1

    if args.command == "validate-package":
        result = validate_package(args.package, schema_dir=args.schema_dir)
        print_result(
            result,
            output_format=args.format,
            success_message=f"{args.package} package validates",
        )
        return 0 if result.ok else 1

    if args.command == "receipts":
        ledger_path = getattr(args, "sub_ledger", None) or args.ledger
        try:
            if args.receipts_command == "add":
                append_result = append_ledger_entry(ledger_path, args.package, gate=args.gate)
                if args.format == "json":
                    print(json.dumps({"ok": True, **append_result.__dict__}, indent=2, sort_keys=True))
                else:
                    print(f"{append_result.message}: {append_result.entry['package_id']}")
                return 0

            if args.receipts_command == "verify":
                issues = verify_ledger_file(ledger_path)
                if args.format == "json":
                    print(
                        json.dumps(
                            {"ok": not issues, "issues": [issue.as_dict() for issue in issues]},
                            indent=2,
                            sort_keys=True,
                        )
                    )
                elif issues:
                    print("ledger verification failed", file=sys.stderr)
                    for issue in issues:
                        print(f"- {issue.path}: {issue.message}", file=sys.stderr)
                else:
                    print(f"{ledger_path} ledger verifies")
                return 0 if not issues else 1

            entries = read_ledger_entries(ledger_path)
            issues = verify_ledger_file(ledger_path) if ledger_path.exists() else []
            if issues:
                if args.format == "json":
                    print(
                        json.dumps(
                            {"ok": False, "issues": [issue.as_dict() for issue in issues]},
                            indent=2,
                            sort_keys=True,
                        )
                    )
                else:
                    print("ledger verification failed", file=sys.stderr)
                    for issue in issues:
                        print(f"- {issue.path}: {issue.message}", file=sys.stderr)
                return 1

            if args.format == "json":
                print(json.dumps({"ok": True, **ledger_summary(entries)}, indent=2, sort_keys=True))
            else:
                print(format_ledger_summary(ledger_path, entries))
            return 0
        except LedgerError as exc:
            if args.format == "json":
                print(json.dumps({"ok": False, "issues": [{"path": str(ledger_path), "message": str(exc)}]}))
            else:
                print(f"receipt ledger error: {exc}", file=sys.stderr)
            return 1

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

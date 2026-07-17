from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import the_pass.validator as validator
from the_pass.cli import build_parser, main


class ValidatorCompatibilityTests(unittest.TestCase):
    def test_compatibility_shim_imports_every_public_name(self) -> None:
        namespace: dict[str, object] = {}
        statement = "from the_pass.validator import " + ", ".join(validator.__all__)
        exec(statement, namespace)
        self.assertEqual(
            set(validator.__all__),
            {name for name in namespace if name != "__builtins__"},
        )

    def test_filename_detection_is_pinned_for_every_registered_type(self) -> None:
        for artifact_type in validator.ARTIFACT_SCHEMAS:
            with self.subTest(artifact_type=artifact_type):
                self.assertEqual(
                    validator.detect_artifact_type(
                        Path(f"{artifact_type}.json"), {"unexpected": True}
                    ),
                    artifact_type,
                )

    def test_registered_schema_key_subsets_do_not_collide(self) -> None:
        intentionally_filename_only = {
            "dataset_plan",
            "dataset_receipt",
            "reproduction_spec",
            "reviewer_attestation",
            "reviewer_key_registry",
            "robustness_report",
        }
        schema_dir = validator.default_schema_dir()
        for artifact_type, versions in validator.ARTIFACT_SCHEMAS.items():
            schema = json.loads(
                (schema_dir / versions[max(versions)]).read_text(encoding="utf-8")
            )
            document = {key: None for key in schema.get("required", [])}
            expected = None if artifact_type in intentionally_filename_only else artifact_type
            with self.subTest(artifact_type=artifact_type):
                self.assertEqual(
                    validator.detect_artifact_type(Path("artifact.json"), document),
                    expected,
                )


class CliHelpSmokeTests(unittest.TestCase):
    def assert_help_exits_zero(self, argv: list[str]) -> None:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as raised:
                main(argv)
        self.assertEqual(raised.exception.code, 0)

    def test_top_level_and_every_command_help(self) -> None:
        self.assert_help_exits_zero(["--help"])
        commands = build_parser()._subparsers._group_actions[0].choices
        for command in commands:
            with self.subTest(command=command):
                self.assert_help_exits_zero([command, "--help"])

# Slash Skill Audit

Date: 2026-07-09.
Scope: `/the-pass:*` skills and their command contracts.

This initial audit is superseded by
[SYSTEM_HARDENING_AUDIT_2026-07-09.md](SYSTEM_HARDENING_AUDIT_2026-07-09.md). Its
textual consistency checks passed, but it did not run the canonical per-skill validator or
verify that every promised output had a registered schema.

## Verdict

`pass after fixes`.

The slash-command skills are now consistent across `docs/plugin/COMMANDS.md`,
`docs/implementation/SKILL_CONTRACTS.md`, and `skills/*/SKILL.md`.

## Largest Gaps Found

1. `taste` used `block` while the rest of the system uses `blocked`.
   - Fixed by changing `taste` exit states and command docs to `blocked`.
   - This now aligns with `verdict_report` enum and the shared rule that missing evidence returns `blocked`.

2. Several slash skills promised structured outputs without templates.
   - Fixed by adding templates for screen reports, findings, refire tickets, simmer laps,
     paper plans, observation manifests, divergence reports, approval packs, and receipt summaries.
   - Updated the relevant skill `Read First` and `Outputs` sections to cite those templates.

3. Several editable output directories were named in skills but not scaffolded.
   - Fixed by adding README placeholders for screen, paper, hypothesis, review, approval,
     receipt-summary, and simmer report directories.
   - Updated `.gitignore` so generated screen and paper experiment outputs are not accidentally tracked.

4. One skill contained a user-specific absolute path for plugin validation.
   - Fixed by replacing it with a portable instruction to run the bundled plugin validator from the local Codex install.

## Command Matrix

| Slash Command | Current State |
| --- | --- |
| `/the-pass:mise` | setup/audit workflow, portable validation instructions |
| `/the-pass:research` | source note and hypothesis workflow |
| `/the-pass:spec` | StrategySpec workflow |
| `/the-pass:screen` | diagnostic screen workflow with `screen_report` template |
| `/the-pass:backtest` | run package workflow |
| `/the-pass:taste` | independent review workflow with `blocked` state |
| `/the-pass:refire` | scoped fix workflow with findings/refire templates |
| `/the-pass:simmer` | focused iteration workflow with lap template |
| `/the-pass:paper` | paper/replay workflow with plan/observation/divergence templates |
| `/the-pass:plate` | approval-pack workflow with approval template |
| `/the-pass:receipts` | ledger summary workflow with receipt summary template |

## Evidence

- Every skill has `Inputs`, `Read First`, `Editable Paths`, `Blocked Paths`, `Procedure`,
  `Required Checks`, `Outputs`, and `Exit States`.
- Command docs and skill contracts use matching skill names and exit states.
- `scripts/validate_public_repo.py` now requires all slash-output templates and workflow directories.
- Public validator, unit tests, package validation, adapter validation, ledger simulation, and plugin validation pass.

---
name: mise
description: "Set up or audit a repository for The Pass workflow: ADRs, templates, artifact folders, public safety, and no-live-trading boundaries."
---

# The Pass Mise

Use this skill when preparing a repo for The Pass or checking whether the repo is ready for
strategy research workflow.

## Inputs

- Repository path or current working directory.
- Optional target scope: new scaffold, audit-only, repair missing files, or public-release check.
- Optional market scope for examples or adapters. Keep the scope diagnostic unless an accepted ADR says otherwise.

## Read First

- `.codex-plugin/plugin.json`
- `README.md`
- `docs/implementation/BUILD_PLAN.md`
- `docs/implementation/SKILL_CONTRACTS.md`
- `docs/implementation/VALIDATION_AND_SAFETY.md`
- `docs/adr/`
- `schemas/`
- `templates/`
- `scripts/validate_public_repo.py`

## Editable Paths

- `.codex-plugin/plugin.json`
- `README.md`
- `CONTRIBUTING.md`
- `SECURITY.md`
- `docs/`
- `schemas/`
- `templates/`
- `skills/`
- `examples/`
- `research/`
- `experiments/README.md`
- `reports/README.md`

## Blocked Paths

- Credential files, private keys, `.env`, wallet files, broker configs, and paid data dumps.
- Live order placement code, live adapter code, or production account identifiers.
- User strategy outputs outside public-safe examples unless the user explicitly asks and the repo policy allows it.

## Procedure

- Do not add real order placement, broker credentials, private keys, or paid data files.
- Prefer public-safe examples and synthetic samples.
- Make setup idempotent: rerunning the skill should not destroy user work.
- Ensure the repo has ADRs, templates, source notes, the two-level
  `experiments/runs/<strategy-id>/<run-id>/` tree, experiment receipts, reports, and a
  public-release checklist.
- Check whether all command skills exist and have valid front matter.
- Check that schemas and templates cover the core artifact package: adapter, source note,
  strategy spec, data manifest, run receipt, metrics report, cost waterfall, and verdict report.
- Check that examples are diagnostic, public-safe, and cannot imply live trading approval.
- Repair missing setup only when the required content is clear. Otherwise create a blocker list.

## Required Checks

Run the strongest available local checks before returning:

```bash
python3 scripts/validate_public_repo.py
python3 -m unittest discover -s tests
```

If the Python package is installed, also run any package validation commands listed in `README.md`.
Codex plugin developers should run the bundled `plugin-creator/scripts/validate_plugin.py`
validator against the repo root from their local Codex install.

## Outputs

- Setup audit with existing, repaired, and missing items.
- Updated docs, schemas, templates, skills, or examples when safe.
- Explicit blocker list when a decision, data boundary, or live-trading approval is missing.

## Exit States

- `ready`: all setup gates pass and no repair was needed.
- `repaired`: missing public-safe scaffold items were created or fixed and checks pass.
- `blocked`: a required decision, artifact, validator, or safety boundary is missing.

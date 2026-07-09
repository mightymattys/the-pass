---
name: simmer
description: "Iterate on a specific measurable gate until it passes, is blocked, or hits a kill condition."
---

# The Pass Simmer

Use this skill for goal-shaped research work such as "make this artifact package pass the
research gate" or "reduce reproducibility failures to zero".

## Inputs

- One target gate or measurable acceptance condition.
- Starting package, StrategySpec, or findings list.
- Iteration budget, stop condition, and kill condition when provided.

## Read First

- Current package artifacts and receipts.
- `templates/simmer_laps.yaml`
- `docs/implementation/SKILL_CONTRACTS.md`
- `docs/implementation/ARTIFACT_LIFECYCLE.md`
- Relevant `taste` findings.

## Editable Paths

- `experiments/runs/<strategy-id>/<run-id>/simmer_laps.yaml`
- Superseding artifacts under `experiments/runs/<strategy-id>/<new-run-id>/`
- `reports/simmer/`
- Narrow code or artifact paths required by the active gate.

## Blocked Paths

- Live order code, credentials, and private data.
- Unrelated strategy improvements.
- The gate definition after iteration starts.

## Procedure

- Define one target gate before starting.
- Keep a lap receipt for each iteration.
- Stop on no-progress, budget, or kill condition.
- Do not reinterpret the gate after seeing results.
- At the start of each lap, record hypothesis, intended change, files touched, command to run, and expected pass/fail signal.
- After each lap, record artifact paths, validation output, metric changes, blockers, and whether the lap moved the target gate.
- If two consecutive laps do not move the target gate, recommend blocked or kill instead of continuing blindly.
- Use `refire` for confirmed defects and `taste` for independent gate review.

## Required Checks

Run the target gate command every lap. For package gates:

```bash
the-pass validate <simmer-laps> --type simmer_laps
the-pass validate-package <package-dir>
the-pass receipts add <package-dir> --gate <gate-name>
the-pass receipts verify
```

## Outputs

- Gate target.
- Iteration receipts based on `templates/simmer_laps.yaml`.
- Final status: passed, blocked, killed, or needs human decision.

## Exit States

- `passed`: the predefined gate passes with validating artifacts.
- `blocked`: required evidence, data, decision, or tooling is missing.
- `killed`: kill criteria are met or iteration budget is exhausted without progress.

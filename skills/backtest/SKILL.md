---
name: backtest
description: "Design or run a reproducible backtest package with manifest, receipt, metrics, cost waterfall, and verdict artifacts."
---

# The Pass Backtest

Use this skill for full reproducible strategy tests.

## Inputs

- Valid `StrategySpec`.
- Data manifest or public-safe fixture data.
- Runner configuration, code version, random seed, cost model, and fill model.
- Optional adapter artifact. Public packages must keep adapter safety flags false.

## Read First

- `templates/data_manifest.yaml`
- `templates/run_receipt.yaml`
- `templates/metrics_report.yaml`
- `templates/cost_waterfall.yaml`
- `templates/verdict_report.yaml`
- Matching schemas in `schemas/`
- `docs/implementation/ARTIFACT_LIFECYCLE.md`
- `docs/adapter-contract.md`

## Editable Paths

- `experiments/runs/<strategy-id>/<run-id>/`
- `reports/`
- `examples/**/package/` for public-safe fixtures.
- `data/normalized/` only for public-safe or user-approved normalized fixtures.

## Blocked Paths

- Raw paid data, private fills, credentials, live adapter configs, and live order placement code.
- Existing run packages, except to add missing metadata when the user explicitly asks. Prefer new run IDs.

## Procedure

- Every backtest needs a data manifest and run receipt.
- Promotion tests must use pessimistic fills and explicit costs.
- Record event time, receive time, decision time, and simulated execution timing when
  available.
- If data, cost, or fill assumptions are incomplete, mark the verdict `blocked`.
- Produce a complete run package, not loose screenshots or prose.
- Include gross and net metrics. If either cannot be calculated, set it explicitly to `null`
  and explain why in limitations.
- Include a null or random baseline when the test is meant to inform promotion. If absent, the verdict cannot pass.
- Preserve all previous packages; create a new package or rerun receipt for changed code, data, or config.
- Public examples must remain diagnostic and must not imply real edge.

## Required Checks

```bash
the-pass validate-package <package-dir>
the-pass receipts add <package-dir> --gate <gate-name>
the-pass receipts verify
```

## Outputs

- Data manifest.
- Run receipt.
- Metrics report.
- Cost waterfall.
- Verdict report.

## Exit States

- `complete`: package validates and the verdict artifact states the gate result.
- `blocked`: required data, costs, fill assumptions, safety flags, or reproducibility evidence are missing.

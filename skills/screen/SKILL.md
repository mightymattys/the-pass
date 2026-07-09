---
name: screen
description: "Design or run a fast diagnostic strategy screen with conservative costs, null baselines, and no promotion claims."
---

# The Pass Screen

Use this skill for early diagnostic screens before a full event-driven backtest.

## Inputs

- `StrategySpec` or research hypothesis.
- Optional data manifest and lightweight runner configuration.
- Cost, slippage, latency, and null baseline assumptions.

## Read First

- `templates/strategy_spec.yaml`
- `templates/data_manifest.yaml`
- `templates/screen_report.yaml`
- `docs/implementation/SKILL_CONTRACTS.md`
- `docs/implementation/VALIDATION_AND_SAFETY.md`

## Editable Paths

- `experiments/screens/<screen-id>/screen_report.yaml`
- `experiments/screens/<screen-id>/data_manifest.yaml`
- `experiments/screens/<screen-id>/run_receipt.yaml`
- `reports/screens/`
- `examples/**/` for public-safe diagnostic fixtures.

## Blocked Paths

- Promotion verdicts, live adapters, credentials, and real order paths.
- Full backtest package artifacts unless the user asks to escalate to `backtest`.

## Procedure

- Screens are not promotion evidence.
- Mid-price or bar-close assumptions must be labeled diagnostic-only.
- Include gross and net results with conservative costs.
- Record all tried variants.
- Define the null or random baseline before running the screen.
- Record sample start/end, filters, parameter grid, number of variants, and all rejected variants.
- Use pessimistic costs. If costs are unavailable, mark the screen `blocked` or `revise`, not `backtest_candidate`.
- Escalate only when the diagnostic survives costs, beats the baseline, and has a plausible route to an event-driven package.

## Required Checks

```bash
the-pass validate <screen-report> --type screen_report
the-pass validate <data-manifest> --type data_manifest
```

## Outputs

- Screen plan or screen report based on `templates/screen_report.yaml`.
- Null/random baseline comparison.
- Verdict: reject, revise, or escalate to backtest.

## Exit States

- `reject`: diagnostic evidence fails baseline, costs, or basic robustness.
- `revise`: the idea may be fixable but needs better specification or data.
- `backtest_candidate`: diagnostic evidence justifies a full reproducible package.
- `blocked`: required data, costs, or assumptions are missing.

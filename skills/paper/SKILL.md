---
name: paper
description: "Prepare or review paper/replay trading observation with the same decision code, cost assumptions, and risk gates as research."
---

# The Pass Paper

Use this skill when a candidate is ready for paper/replay observation.

## Inputs

- Backtest package whose `verdict_report.verdict` is `paper_candidate` and whose receipt
  ledger verifies.
- Candidate StrategySpec, adapter artifact, config hash, and observation window.
- Divergence thresholds and stop conditions.

## Read First

- Prior package artifacts and verdict.
- `templates/paper_plan.yaml`
- `templates/observation_manifest.yaml`
- `templates/divergence_report.yaml`
- `docs/implementation/SKILL_CONTRACTS.md`
- `docs/adapter-contract.md`
- `docs/implementation/VALIDATION_AND_SAFETY.md`

## Editable Paths

- `experiments/paper/<paper-id>/paper_plan.yaml`
- `experiments/paper/<paper-id>/observation_manifest.yaml`
- `experiments/paper/<paper-id>/divergence_report.yaml`
- `reports/paper/`

## Blocked Paths

- Broker credentials, private keys, real order placement code, and live account configs.
- Live approval packs. Use `plate` only after paper evidence exists.

## Procedure

- Paper is not live trading.
- Use the same decision logic as the accepted backtest where possible.
- Track paper-vs-backtest divergence.
- No broker credentials or real order paths in public repo artifacts.
- Verify that the package's `verdict_report.verdict` equals `paper_candidate` and that
  `the-pass receipts verify --ledger <ledger-path>` passes.
- Before returning `paper_ready`, confirm the package's `package_id` appears at
  `research_gate` in `the-pass receipts --ledger <ledger-path>`. If either receipt check
  fails, return `blocked`.
- Document every difference between backtest and paper decision logic before observation starts.
- Set divergence thresholds, observation length, kill switches, and missing-data policies before observing results.
- Record that generated paper orders are simulated intents only and cannot reach a broker or venue.

## Required Checks

```bash
the-pass validate-package <source-package>
the-pass validate <paper-plan> --type paper_plan
the-pass validate <observation-manifest> --type observation_manifest
the-pass validate <divergence-report> --type divergence_report
the-pass receipts verify --ledger <ledger-path>
the-pass receipts --ledger <ledger-path>
```

## Outputs

- Paper plan based on `templates/paper_plan.yaml`.
- Observation manifest based on `templates/observation_manifest.yaml`.
- Divergence report requirements based on `templates/divergence_report.yaml`.
- Gate criteria for risk review.

## Exit States

- `paper_ready`: plan is artifact-backed, uses the same decision logic, and cannot place real orders.
- `blocked`: the source verdict is not `paper_candidate`, receipt verification fails,
  divergence policy is missing, the adapter is unsafe, or live paths/credentials appear.

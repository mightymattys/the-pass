---
name: taste
description: "Independently review a strategy package for data leakage, overfitting, weak execution assumptions, risk issues, and promotion blockers."
---

# The Pass Taste

Use this skill when reviewing an experiment package, backtest, paper report, or gate pack.

## Inputs

- Package directory or artifact bundle.
- Target gate: `research_gate`, `paper_gate`, `risk_review`, or `live_gate`.
- Optional prior findings and known constraints.

## Read First

- All artifacts in the package.
- `templates/verdict_report.yaml`
- `templates/findings.yaml`
- `templates/refire_ticket.yaml`
- `docs/implementation/SKILL_CONTRACTS.md`
- `docs/implementation/VALIDATION_AND_SAFETY.md`
- `docs/implementation/ARTIFACT_LIFECYCLE.md`
- Relevant adapter contract and ADRs.

## Editable Paths

- `experiments/runs/<strategy-id>/<run-id>/verdict_report.yaml`
- `reports/reviews/`
- `experiments/runs/<strategy-id>/<run-id>/findings.yaml`
- `experiments/runs/<strategy-id>/<run-id>/refire_ticket.yaml`
- `examples/**/package/verdict_report.json` for public-safe fixtures.

## Blocked Paths

- Strategy thesis rewrites, data edits, backtest code changes, credentials, live configs, and order placement.
- Any artifact needed to prove a finding unless the user asks for `refire`.

## Procedure

- Lead with findings, ordered by severity.
- Validate claims against artifacts, not summaries.
- Check data manifest, run receipt, source notes, metrics, cost waterfall, and verdict.
- Confirm whether each finding blocks promotion.
- Run package validation before reviewing results. A validation failure blocks promotion.
- Check timestamp integrity, lookahead controls, train/test separation, sample size, multiple testing, and parameter stability.
- Check gross-to-net degradation, fee/slippage/impact/funding assumptions, rejected fills, latency, and liquidity limits.
- Compare against null or random baselines. Missing baseline blocks promotion unless a documented reason is artifact-backed.
- Review safety flags. Any live order path, credentials, or live-trading flag in a public package blocks promotion.
- Update or create a verdict report when the current verdict does not match the findings.
- The exit state is the value written to `verdict_report.verdict`. A successful
  `research_gate` review exits `paper_candidate`; later gates record their decisions in
  their own workflow artifacts and never expand the core verdict enum.

## Review Areas

- Data leakage and timestamp errors.
- Multiple testing and overfitting.
- Unrealistic fills, fees, slippage, impact, or latency.
- Missing null baseline.
- Risk, drawdown, and tail exposure.
- Public/private safety boundary.

## Required Checks

```bash
the-pass validate-package <package-dir>
the-pass validate <findings> --type findings
```

If a verdict changes, validate again and add a receipt:

```bash
the-pass receipts add <package-dir> --gate <gate-name>
the-pass receipts verify
```

## Outputs

- Findings with file references.
- Gate result and `verdict_report.verdict`: `paper_candidate`, `blocked`, `revise`, or
  `kill`.
- Findings based on `templates/findings.yaml`.
- Refire ticket based on `templates/refire_ticket.yaml` for confirmed fixable issues.

## Exit States

- `paper_candidate`: artifacts validate, required evidence exists, and no blocker remains. Public diagnostic packages cannot use this for live approval.
- `blocked`: missing or weak evidence prevents promotion.
- `revise`: fixable implementation or artifact issues require `refire`.
- `kill`: the thesis, data, execution assumptions, or robustness evidence fail the gate.

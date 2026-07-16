---
name: plate
description: "Prepare risk evidence and a pending human-decision approval pack after paper_gate, then hand the exact immutable package to an independent risk review without granting live approval."
---

# The Pass Plate

Use this skill after an exact package has a recorded passed `paper_gate`. Plate prepares the inputs
for `risk_review`; it does not perform that independent gate and never approves live trading.

## Inputs

- Passed paper package and shared ledger.
- Returns, stress scenarios, asset class, capacity, versioned risk policy, and unresolved blockers.
- Exact config hash, config diff, adapter, limits, monitoring, rollback, and incident runbook.
- Named pending human decisions and a new risk package/run ID.

## Read First

- Prior research and paper decisions for the source package.
- `templates/risk_policy.yaml`
- `templates/risk_report.yaml`
- `templates/config_diff.yaml`
- `templates/approval_pack.yaml`
- `docs/implementation/ROBUSTNESS_RISK_AUDIT.md`
- `docs/implementation/VALIDATION_AND_SAFETY.md`

## Editable Paths

- Risk working evidence and redacted summaries under `reports/`.
- One new superseding package under `experiments/runs/<strategy-id>/<risk-run-id>/`.
- New run receipt after every required risk/approval artifact is finalized in the package root.

## Blocked Paths

- Recorded paper package, prior gate decisions, StrategySpec thesis, credentials, account details,
  real order code, and approved human-decision state.
- `live_gate` evaluation or any pack claiming to grant approval.

## Agent Delegation

- Delegation is limited to read-only review of completed risk and approval inputs under
  `docs/plugin/CROSS_RUNTIME.md`.
- No agent may set a human decision to accepted, modify limits, write approval state, authorize a
  live capability, or alter the exact package.
- Treat delegated analysis as a finding input, never as approval or gate passage.

## Procedure

- Verify exact passed `paper_gate` membership for the source package and verify the ledger.
- Build strategy-independent risk policy/report from returns and scenarios. Strategy code cannot
  modify limits.
- Create a superseding risk package and copy required paper evidence into its root.
- Add risk report, config diff, and approval pack to the exact package root.
- Compute the final package identity after all promotion evidence exists. Rebuild the risk report
  with that package ID; changing only `risk_report.package_id` must not change the identity.
- Require matching package ID, policy/config hashes, max notional/loss/drawdown, kill switches,
  monitoring, rollback, incident runbook, capacity, and evidence links.
- Keep every human decision `pending`; preserve external decisions only as linked evidence.
- Validate the complete package, append its run receipt, and verify the ledger.
- Re-evaluate and record `research_gate` and `paper_gate` for this exact risk package ID before
  handing it to independent `/the-pass:review` for `risk_review`.
- If live approval, credentials, or real order transport is requested, return `forbidden`.

## Required Checks

```bash
the-pass risk build --returns <returns> --scenarios <scenarios> --package-id <package-id> \
  --asset-class <asset-class> --capacity <capacity> --output-dir <risk-work-dir>
the-pass workflow supersede <paper-package> <risk-package> \
  --ledger <ledger> --run-id <risk-run-id> --created-at <rfc3339> \
  --trusted-reviewers <trusted-registry>
the-pass workflow fingerprint <risk-package>
the-pass validate <risk-package>/risk_report.yaml --type risk_report
the-pass validate <risk-package>/config_diff.yaml --type config_diff
the-pass validate <risk-package>/approval_pack.yaml --type approval_pack
the-pass validate-package <risk-package>
the-pass receipts add <risk-package> --ledger <ledger> \
  --trusted-reviewers <trusted-registry>
the-pass receipts verify --ledger <ledger> --trusted-reviewers <trusted-registry>
```

## Outputs

- Versioned risk policy/report, config diff, and approval pack.
- Immutable risk successor package with all human decisions pending.
- Verified run receipt and exact handoff to independent `risk_review`.
- Missing evidence or forbidden-operation report.

## Exit States

- `packaged`: the exact risk package validates, is recorded, and is ready for independent review.
- `blocked`: prior gates, risk, config, operations, package, owner, or ledger evidence is missing.
- `forbidden`: the request attempts live approval, credentials, real orders, or non-pending human state.

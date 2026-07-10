---
name: review
description: "Independently audit a strategy package for data, statistics, execution, risk, paper divergence, and operations, then evaluate the exact requested non-live gate without implementing fixes."
---

# The Pass Review

Use this skill for a fresh, independent review of `research_gate`, `paper_gate`, or `risk_review`
evidence. It replaces `taste` and routes checks by the actual target gate.

## Inputs

- Exact package root, shared ledger, target gate, gate policy, and reviewer identity.
- StrategySpec owner and run owner, both present in package artifacts.
- Optional prior findings, audit focus, and reproduction command.

## Read First

- Every artifact in the exact package root and every prior decision for its package ID.
- `templates/findings.yaml`
- `templates/audit_report.yaml`
- `templates/gate_decision.yaml`
- `docs/implementation/ROBUSTNESS_RISK_AUDIT.md`
- `docs/implementation/VALIDATION_AND_SAFETY.md`
- `config/gate-policies.v1.yaml`

## Editable Paths

- New findings, audit report, verdict, and gate decision inside an unrecorded review package.
- `reports/reviews/` for read-only review summaries.
- New append-only gate-decision entries after evaluation.

## Blocked Paths

- Strategy implementation, thesis, source data, search space, cost inputs, credentials, and live code.
- Any package already fingerprinted by a receipt. Create a successor before adding review artifacts.
- Existing receipts or decisions. Reviewer and implementer roles must not be combined.

## Procedure

### Independence preflight

- Require reviewer, StrategySpec owner, and run owner.
- Block if reviewer equals either owner or no independent read-only context exists.
- Validate the package and ledger before interpreting results.
- Scope findings to artifact evidence and label severity, status, recommendation, and promotion
  impact. Refuted findings do not become remediation tickets.

### Research gate

- Check source classification, data chronology, leakage, holdouts, baselines, sample size,
  multiple testing, parameter sensitivity, reproducibility, fills, costs, accounting, stress, and
  strategy-independent risk.
- Run robustness and risk CLI operations when their structured inputs exist.
- A pass requires `verdict_report.verdict: paper_candidate`, independent findings with no blocker,
  and exact package evidence.

### Paper gate

- Require exact passed `research_gate` membership for the same package ID.
- Check paper plan, minimum observation window, signal/trade threshold, decision-code parity,
  latency, fills, costs, outages, incidents, and divergence breaches.
- Write `audit_report.paper_gate.<json|yaml>` in the package root and tie its reviewer and target
  to the gate invocation.
- Incomplete observation is blocked/waiting evidence, never a pass.

### Risk review

- Run only after risk preparation and `/the-pass:plate` created `risk_report`, `approval_pack`,
  and `config_diff` in the exact package root.
- Require exact passed `paper_gate`, matching config and policy hashes, limits, monitoring,
  rollback, incident runbook, capacity, and pending human decisions.
- Write `audit_report.risk_review.<json|yaml>` in the package root and tie its reviewer and target
  to the gate invocation.
- This gate approves evidence readiness only. It cannot approve live trading.

### Decision and recording

- Validate findings and audit artifacts before gate evaluation.
- Evaluate the requested gate, not a hard-coded gate.
- Append only the resulting artifact-backed decision; duplicate append is idempotent success.
- Verify the ledger after append. Any append/verification failure returns `blocked`.
- Confirmed fixable findings return `revise`; implementation belongs to `/the-pass:run` remediation.

## Required Checks

Research statistics and risk when applicable:

```bash
the-pass robustness evaluate --matrix <return-matrix> --selected-index <index> \
  --output <robustness-report>
the-pass risk build --returns <returns> --scenarios <scenarios> --package-id <package-id> \
  --asset-class <asset-class> --capacity <capacity> --output-dir <risk-dir>
```

Review and gate decision:

```bash
the-pass validate-package <package>
the-pass validate <findings> --type findings
the-pass validate <audit-report> --type audit_report
the-pass gate evaluate <package> --gate <target-gate> --reviewer <reviewer> \
  --policy <policy> --ledger <ledger> --output <package>/gate_decision.<target-gate>.yaml
the-pass receipts add-decision <package>/gate_decision.<target-gate>.yaml --ledger <ledger>
the-pass receipts verify --ledger <ledger>
```

`live_gate` is a safety test only and must return forbidden/exit 3.

## Outputs

- Independent findings and audit report with exact evidence paths.
- Gate-specific verdict: pass, blocked, revise, or kill.
- Separately validated and recorded gate decision on pass or valid non-promotion outcome.
- Exact remediation scope or next evidence requirement.

## Exit States

- `passed`: the requested non-live gate passed and its exact decision is recorded.
- `blocked`: evidence, owner independence, package, ledger, or policy requirements are missing.
- `revise`: confirmed fixable findings require a superseding package and new review.
- `kill`: the thesis or candidate hits a predefined kill condition.
- `forbidden`: the request targets or implies live approval or another prohibited operation.

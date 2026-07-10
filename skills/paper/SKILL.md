---
name: paper
description: "Prepare, run, or resume isolated paper observation from an exact passed research package, preserving decision parity and stopping safely on waiting windows, divergence, stale data, outages, or risk breaches."
---

# The Pass Paper

Use this skill only after an exact package has a recorded passed `research_gate` decision.

## Inputs

- Passed research package, package ID, ledger, StrategySpec, adapter, and exact config hash.
- Paper observation thresholds, minimum window/signals/trades, and stop conditions.
- Canonical events, versioned risk policy, and supported strategy decision code.
- New successor package and paper run IDs.

## Read First

- Prior package and exact `research_gate` decision.
- `templates/paper_plan.yaml`
- `templates/observation_manifest.yaml`
- `templates/divergence_report.yaml`
- `docs/implementation/PAPER_AUTOMATION_REPORTING.md`
- `docs/implementation/ARTIFACT_LIFECYCLE.md`
- `docs/implementation/VALIDATION_AND_SAFETY.md`

## Editable Paths

- Canonical working evidence under `experiments/paper/<paper-id>/` and `reports/paper/`.
- One new superseding package under `experiments/runs/<strategy-id>/<paper-run-id>/`.
- New run receipt in the shared ledger after package finalization.

## Blocked Paths

- Recorded source package, StrategySpec thesis, historical decisions, credentials, user channels,
  real order clients, live configs, and approval state.
- Paper start without exact research-gate membership for the successor evidence chain.

## Procedure

- Verify source package and shared ledger before creating paper state.
- Create a superseding package; never add paper files to the recorded research package.
- Predeclare observation window, sample threshold, divergence limits, missing-data policy, outage
  policy, clock-skew policy, and freeze conditions.
- Use the same decision code and config hash as accepted research, or document every difference
  before observation starts.
- Run only the isolated virtual paper process. No credentials or network clients enter the worker.
- Record decisions, simulated intents, fills, missed fills, costs, latency, outages, and risk events.
- Freeze on stale data, clock skew, outage, or risk breach.
- Return `waiting` while a valid minimum window is incomplete. Do not compress elapsed time or
  manufacture observations.
- Build and validate paper plan, observation manifest, and divergence report. Copy all three into
  the exact successor package root before finalization.
- Keep the successor mutable and unrecorded while observation is waiting. Once the predefined
  window is complete, append the finalized successor and verify the ledger.
- `/the-pass:review` must evaluate and record a fresh `research_gate` for the exact paper package
  ID before evaluating `paper_gate`.

## Required Checks

```bash
the-pass workflow supersede <research-package> <paper-package> \
  --ledger <ledger> --run-id <paper-run-id> --created-at <rfc3339>
the-pass paper run --strategy <supported-strategy> --events <events> \
  --risk-policy <risk-policy> --observation-time-ns <time> \
  --max-staleness-ns <limit> --max-clock-skew-ns <limit> \
  --max-outage-gap-ns <limit> --output <paper-result>
the-pass validate <paper-package>/paper_plan.yaml --type paper_plan
the-pass validate <paper-package>/observation_manifest.yaml --type observation_manifest
the-pass validate <paper-package>/divergence_report.yaml --type divergence_report
the-pass validate-package <paper-package>
the-pass receipts add <paper-package> --ledger <ledger>
the-pass receipts verify --ledger <ledger>
```

If the decision code is unsupported by the reference worker, return `blocked`; do not substitute a
different strategy.

## Outputs

- Valid paper plan, observation manifest, decision journal, and divergence report.
- Immutable paper successor package and verified run receipt.
- Waiting progress or fail-closed incident/freeze evidence.
- Exact next action for independent paper-gate review.

## Exit States

- `paper_ready`: paper artifacts and finalized successor package validate and are recorded.
- `waiting`: the observation is healthy but its predefined minimum window is incomplete.
- `blocked`: prior gate, adapter, data, decision parity, package, or ledger evidence is missing.
- `frozen`: stale data, outage, clock skew, divergence, or risk breach stopped observation.

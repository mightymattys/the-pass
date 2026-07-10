---
name: status
description: "Verify and summarize workflow state, immutable receipts, gate decisions, incidents, blockers, and next actions, with optional read-only static report or dashboard generation."
---

# The Pass Status

Use this skill when the user asks what ran, what passed, what failed, what is waiting, or what
evidence is required next. It replaces the public `receipts` skill; the Python receipt CLI remains.

## Inputs

- Repository, `.the-pass` workflow state, ledger, package, strategy ID, or run ID.
- Optional filters for date, owner, gate, verdict, incident, or status.
- Optional request for a static report or dashboard.

## Read First

- Workflow state when present.
- Selected ledger and all referenced artifacts.
- `templates/receipt_summary.yaml`
- `docs/implementation/ARTIFACT_LIFECYCLE.md`
- `docs/public/CLI_CONTRACT.md`

## Editable Paths

- New summaries under `reports/receipt_summaries/`.
- Generated read-only report/dashboard bundles under `reports/generated/`.
- No workflow or ledger writes during status-only operation.

## Blocked Paths

- Existing workflow state, ledger entries, packages, gate decisions, limits, StrategySpecs, and
  approval state.
- Credentials, private data, and live logs.

## Procedure

- Validate workflow state when supplied.
- Verify the entire ledger and referenced artifact bytes before summarizing any promotion claim.
- Stop at the first broken chain/artifact and return `blocked`; do not summarize untrusted later
  entries as valid.
- Separate framework capability status from candidate gate status.
- Report current stage, target gate, last exact passed gate, package ID, verdict, open blockers,
  incidents, budget use, and next action.
- Treat duplicate receipts as one idempotent package event, not multiple experiments.
- Build reports and dashboards only from verified artifacts. They remain read-only.

## Required Checks

```bash
the-pass workflow status --state <state>
the-pass receipts verify --ledger <ledger>
the-pass receipts --ledger <ledger> --format json
the-pass validate <receipt-summary> --type receipt_summary
```

Optional reporting:

```bash
the-pass report build --repo-root <repo> --output-dir <report-dir>
the-pass dashboard build --repo-root <repo> --output-dir <dashboard-dir>
```

## Outputs

- Verified workflow and ledger summary.
- Candidate/framework distinction, blockers, incidents, budgets, and next action.
- Optional static read-only report/dashboard paths.

## Exit States

- `summarized`: state and ledger verify and every claim links to exact evidence.
- `blocked`: state, ledger, referenced artifact, or requested package cannot be verified.

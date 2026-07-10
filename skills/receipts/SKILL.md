---
name: receipts
description: "Summarize The Pass run receipts, evidence artifacts, gate decisions, and unresolved risks."
---

# The Pass Receipts

Use this skill when the user asks what happened, what passed, what failed, or what evidence
exists for a strategy or repo.

## Inputs

- Ledger path, repository path, package directory, or strategy ID.
- Optional filter: date range, gate, verdict, owner, or strategy.

## Read First

- `experiments/ledger.jsonl` or the provided ledger path.
- Relevant package artifacts referenced by ledger entries.
- `templates/receipt_summary.yaml`
- `src/the_pass/ledger.py` for current ledger semantics.
- `docs/implementation/ARTIFACT_LIFECYCLE.md`

## Editable Paths

- `experiments/ledger.jsonl`
- `reports/receipt_summaries/`
- `examples/**/package/` only when adding fixture receipts in CI or docs.

## Blocked Paths

- Existing ledger entries. The ledger is append-only.
- Artifacts referenced by prior receipts unless the user explicitly asks for a repair and a new receipt.
- Credentials, private run outputs, and live order logs.

## Procedure

- Claims without artifacts are not evidence.
- Summarize receipts by date, strategy, gate, verdict, and cost/risk notes.
- Flag missing manifests, metrics, cost waterfalls, or verdict reports.
- Verify ledger hash-chain integrity before summarizing.
- When adding a package, use the CLI so package ID, fingerprints, and chain hashes are deterministic.
- If verification fails, stop and report the first broken entry before making claims from the ledger.
- Link each promotion claim to the exact package ID and verdict.

## Required Checks

```bash
the-pass receipts verify --ledger <ledger-path>
the-pass receipts --ledger <ledger-path>
the-pass validate <receipt-summary> --type receipt_summary
```

When appending a run:

```bash
the-pass receipts add <package-dir> --ledger <ledger-path>
```

When appending a separately evaluated gate decision:

```bash
the-pass receipts add-decision <gate-decision> --ledger <ledger-path>
```

## Outputs

- Receipt table or concise ledger summary based on `templates/receipt_summary.yaml`.
- Promotion status.
- Open blockers and next actions.

## Exit States

- `summarized`: ledger verifies and the requested summary is artifact-backed.
- `blocked`: ledger verification fails, referenced artifacts are missing, or the requested package does not validate.

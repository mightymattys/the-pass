---
name: refire
description: "Fix confirmed The Pass review findings without expanding scope or changing the strategy thesis."
---

# The Pass Refire

Use this skill after `taste` confirms actionable issues.

## Inputs

- Confirmed `taste` findings, refire ticket, or failing validation output.
- Affected package, strategy spec, code path, or artifact path.
- Target gate and verification command.

## Read First

- The finding source and exact blocking evidence.
- Current package artifacts.
- `templates/findings.yaml`
- `templates/refire_ticket.yaml`
- `docs/implementation/ARTIFACT_LIFECYCLE.md`
- `docs/implementation/VALIDATION_AND_SAFETY.md`

## Editable Paths

- The narrow files named by the confirmed finding.
- `experiments/runs/<strategy-id>/<run-id>/` for superseding artifacts and rerun receipts.
- `reports/reviews/` for verification notes.
- Tests that directly cover the finding.

## Blocked Paths

- Strategy thesis changes that make results look better.
- Unrelated refactors, broad schema changes, credentials, live configs, and order placement code.
- Previous receipt entries. Create a new receipt for a rerun.

## Procedure

- Fix only confirmed findings.
- Do not change the strategy thesis to fit results.
- Preserve old artifacts and create new receipts for reruns.
- Re-run the specific checks that prove the finding is fixed.
- Keep the patch scoped to the finding. If a second issue appears, record it as a separate finding.
- When fixing an artifact package, update the run receipt, verdict, or findings file so the audit trail is explicit.
- If the fix changes data, code, config, costs, or fill assumptions, produce a superseding run package or receipt.

## Required Checks

Run the command named by the finding. For package issues, default to:

```bash
the-pass validate-package <package-dir>
the-pass receipts add <package-dir> --gate <gate-name>
the-pass receipts verify
```

Review the refire ticket against its template; it is a review-only artifact.

## Outputs

- Patch or artifact update.
- Verification commands or evidence.
- Refire ticket based on `templates/refire_ticket.yaml`.
- Updated verdict if the gate status changed.

## Exit States

- `fixed`: the targeted finding is resolved and verification passes.
- `still_blocked`: the finding remains, verification cannot run, or the fix would require changing the thesis.

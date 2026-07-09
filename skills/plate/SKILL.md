---
name: plate
description: "Prepare the next-gate approval pack after a candidate has passed research, backtest, taste, and paper requirements."
---

# The Pass Plate

Use this skill to prepare an approval pack. `plate` does not approve live trading; it only
packages evidence for the next human-controlled gate.

## Inputs

- Paper package, risk package, or candidate bundle.
- Exact adapter ID, config hash, strategy ID, and requested next gate.
- Human decision requirements and risk constraints.

## Read First

- All prior receipts and verdict reports.
- Paper observation outputs.
- Risk limits, rollback plan, and monitoring plan.
- `templates/approval_pack.yaml`
- `docs/implementation/VALIDATION_AND_SAFETY.md`
- Accepted live-capability ADRs, if any.

## Editable Paths

- `reports/approval_packs/<strategy-id>/approval_pack.yaml`
- `reports/approval_packs/<strategy-id>/decision_log.md`
- Redacted public summaries under `reports/`.

## Blocked Paths

- Live credentials, wallet keys, broker configs, private account IDs, and real order placement code.
- Prior evidence artifacts except to add links from the approval pack.

## Procedure

- Include exact config hash and artifact links.
- Include risk limits, rollback plan, monitoring plan, and unresolved risks.
- Live approval must be explicit, dated, and tied to an exact adapter and config hash.
- Public packs must redact secrets, account identifiers, and proprietary data.
- Package evidence; do not grant approval.
- Keep every entry in `human_decisions_required` at `pending`. Preserve externally supplied
  decisions as linked evidence; never manufacture or change human approval state.
- Verify that every claimed passed gate points to a receipt and verdict.
- List unresolved risks and required human decisions prominently.
- If any approval-critical artifact is missing, return `blocked`.

## Required Checks

```bash
the-pass validate <approval-pack> --type approval_pack
the-pass receipts verify
the-pass receipts
```

## Outputs

- Approval pack based on `templates/approval_pack.yaml`.
- Missing evidence.
- Human decisions required.

## Exit States

- `packaged`: evidence pack is complete and ready for a human-controlled decision.
- `blocked`: exact config, adapter, risk limit, rollback, monitoring, receipt, or human decision evidence is missing.

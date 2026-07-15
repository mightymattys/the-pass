# The Pass v0.13.0

Version 0.13.0 closes three trust-boundary gaps in dataset provenance, executable-code isolation,
and reviewer identity without adding any live-order capability.

## Highlights

- Dataset receipts v2 bind every committed chunk to its request, raw response, normalized events,
  quality report, manifest, receipt, and commit marker. Resume and replay revalidate the full bundle.
- Automated Codex/Claude workflow stages execute in a detached worktree. The caller receives only a
  validated patch within the stage evidence scope, followed by an atomic state transition.
- Custom strategies expose two honest trust modes. `trusted_local` is diagnostic and reports no OS
  network/filesystem enforcement. `hardened` requires an operator-supplied sandbox launcher and
  matching fingerprinted attestation.
- Reviewer attestations v2 use Ed25519 and a versioned public-key registry. Gate and ledger replay
  require no private key or secret environment variable.
- Automated review prepares evidence but cannot approve itself. The workflow stops at `waiting`
  until the designated reviewer signs the exact review evidence.

## Compatibility

Existing dataset-receipt v1, reproduction-spec v1, and reviewer-attestation v1 evidence remains
readable. New datasets and reproductions emit v2. Legacy HMAC reviewer evidence is historical only
and cannot authorize a new promotion pass.

The CLI changes are additive. Existing `backtest run` calls use `trusted_local`; hardened execution
requires both `--runtime-mode hardened` and `--sandbox-launcher`. Existing gate evaluation can still
return a valid blocked decision without a new attestation.

## Operator Notes

Generate reviewer keys with `the-pass gate keygen`. Keep the mode-`0600` private key outside the
repository and distribute the public registry through an independently reviewed identity process.
Signing reads `THE_PASS_REVIEW_SIGNING_KEY`; verification never does.

The public core still has no authenticated venue client, credential loader, real order transport,
or unlocked `live_gate`.

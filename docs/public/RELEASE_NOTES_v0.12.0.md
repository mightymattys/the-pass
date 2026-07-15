# The Pass v0.12.0

Version 0.12.0 hardens the path from market-data acquisition to independently reviewed evidence.

## Highlights

- Workflow drivers now write isolated proposals. A per-state supervisor lock validates and
  atomically commits one transition; failed drivers cannot consume canonical workflow state.
- `the-pass data plan` and `the-pass data build` provide deterministic chunking, interruption
  resume, conflicting-duplicate quarantine, cross-check policy, and fully revalidated immutable
  dataset publication.
- Custom strategy packages now include a `reproduction_spec` and minimum replay inputs.
  `the-pass audit reproduce` rebuilds them in a clean temporary workspace through a fixed internal
  runner and compares exact artifact fingerprints.
- New promotion passes require a signed `reviewer_attestation` bound to the exact package, gate,
  reviewer, provider/model/run provenance, review evidence, and author/reviewer separation.
- External Codex/Claude dispatch remains serialized within one workspace while unrelated
  workspaces can progress independently.

## Compatibility

Existing one-shot ingest, baseline, paper, package, and ledger evidence remains readable. New gate
evaluations can still return valid blocked decisions without an attestation, but cannot return
`pass`. The public live-order boundary remains locked.

## Operator Note

Automated review supervision reads `THE_PASS_REVIEW_ATTESTATION_KEY` only in the parent and strips
it from child environments. Manual `the-pass gate attest` uses the same variable. Keep the key in a
local secret manager and use at least 32 bytes.

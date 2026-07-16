# The Pass v0.14.0

Version 0.14.0 hardens the scientific and authorization boundary of strategy promotion.

## Highlights

- `robustness_report.v2` replaces free-form promotion claims with a complete registered matrix and
  validator-side statistical recomputation.
- `the-pass candidate assemble` creates an immutable research candidate without hand-editing
  metrics or verdict JSON and records a validator-recomputed assembly manifest in the run receipt.
- Reviewer signatures require an operator-controlled registry outside the package. Creating a key
  no longer authorizes it.
- Hardened strategy execution requires an allowlisted launcher policy and active filesystem,
  loopback-network, and resource-limit probes.
- Review agents can no longer modify scientific package evidence.

## Compatibility

- Existing blocked, killed, and diagnostic packages remain readable.
- Existing v1/v2 historical ledger rows remain readable, but replaying a passed v2 gate now requires
  its external reviewer trust registry.
- `trusted_local` behavior is unchanged and remains non-promotional.
- Existing `robustness evaluate` remains a diagnostic statistics command. Promotion uses
  `robustness sweep` with generated purged walk-forward folds and `candidate assemble`.

## New Required Inputs

- Hardened runtime: `--sandbox-launcher` and `--sandbox-policy`.
- Gate evaluation and passed-decision ledger replay: `--trusted-reviewers` or
  `THE_PASS_TRUSTED_REVIEWER_REGISTRY`.
- Research candidate assembly: recorded source package, `robustness_report.v2`, and independent
  passing findings.

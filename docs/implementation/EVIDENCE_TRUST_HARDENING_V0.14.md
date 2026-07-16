# Evidence And Trust Hardening v0.14

Status: implemented and verified on 2026-07-16.

## Objective

Close four audit findings that could otherwise create false promotion confidence:

1. robustness claims accepted without derived evidence;
2. self-issued reviewer identity accepted as independent authorization;
3. sandbox attestations accepted without proving enforcement;
4. candidate packages assembled through unrestricted document edits.

## Implemented Contracts

### Robustness

- `robustness_report.v2` is a registered package-evidence artifact.
- Reports bind source package, strategy source, descriptor, execution, events, variants, folds, and
  selection policy.
- Validation recomputes PBO, PSR, DSR, Reality Check/SPA, null performance, and neighbor stability.
- Promotion eligibility additionally requires purged walk-forward folds, all mandatory stresses,
  complete cells, and policy-authorized hardened runtime evidence.
- `paper_candidate` metrics and holdout fields must exactly match the report.

### Reviewer Trust

- Package-local Ed25519 registry snapshots remain signature evidence.
- Authorization requires a matching registry file or directory outside the package.
- `--trusted-reviewers` and `THE_PASS_TRUSTED_REVIEWER_REGISTRY` provide the trust store.
- Gate decisions record registry ID, key ID, registry fingerprint, and trusted status.
- Ledger append and semantic replay require the same trust store.
- Run append, generic successor creation, and candidate assembly expose the same explicit trust
  registry option, so post-gate progression does not depend on ambient environment state.

### Hardened Runtime

- Hardened execution requires an executable launcher and a JSON trust policy.
- The policy allowlists the exact launcher SHA-256 and enforcement requirements.
- Before every strategy worker, a probe attempts forbidden reads, forbidden writes, loopback
  connection, and execution without finite CPU/file-size limits.
- Launcher, policy, probe, and worker attestations are fingerprinted in runtime and reproduction
  evidence.
- `trusted_local` remains explicitly non-promotional.

### Candidate Assembly

- `the-pass candidate assemble` consumes a recorded source run, a valid promotion-eligible
  robustness report, and passing independent findings.
- It creates a ledger-linked successor, copies exact evidence, derives metrics/verdict links, and
  validates the complete package.
- The run receipt stores a deterministic assembly manifest binding source package, robustness
  report, findings, and every derived metrics/verdict field.
- Failed assembly removes the partial target.
- Review-stage agent transactions cannot modify scientific package artifacts.

## Regression Coverage

- Self-issued reviewer registry returns a blocked gate.
- A no-op launcher with a correct self-written attestation fails active probes.
- Changed DSR fails semantic recomputation even after the report fingerprint is regenerated.
- Candidate assembly succeeds only from exact valid inputs and produces a new package identity.
- Full offline unit suite, lint, public-repository validation, build, and installed-wheel checks are
  release gates.

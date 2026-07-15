# Post-Audit Hardening Plan

Status: implemented, verified, merged, and released as `v0.12.0`
Scope: workflow integrity, real-data reproducibility, reviewer authority
Target release: `0.12.0`

## 1. Objective

Close the three highest-risk gaps found by the 2026-07-15 repository audit without
weakening the locked live boundary:

1. A failed or concurrent workflow driver must never mutate canonical workflow state.
2. A real strategy must have a first-class path from resumable market-data acquisition
   to a clean, fingerprint-checked replay.
3. A promotion gate must not accept reviewer independence based only on a different
   text label.

The implementation remains offline by default, Python 3.9/3.12 compatible, engine
neutral, and unable to place real orders.

## 2. Locked Decisions

- Agents write workflow transition proposals, never canonical workflow state.
- The supervisor is the only writer that may commit a validated proposal.
- Workflow commits use a per-state advisory lock and an optimistic source fingerprint.
- External dispatch is serialized per workspace, not globally across unrelated projects.
- Dataset acquisition is represented by an immutable plan split into deterministic chunks.
- Completed chunks are individually committed and may be resumed after interruption.
- A dataset is published only after every chunk validates and aggregate quality is evaluated;
  diagnostic publication preserves a blocked promotion impact instead of hiding the dataset.
- Cross-source evidence is policy-controlled. A required but absent cross-check blocks
  research promotion without blocking diagnostic use.
- Reproduction uses a structured runner specification. It never executes a shell string
  from a receipt.
- Custom-strategy packages carry the minimum immutable inputs required for a clean replay.
- Reviewer attestations are HMAC-SHA256 signed with a 256-bit key supplied only to the
  parent supervisor or explicit gate command through `THE_PASS_REVIEW_ATTESTATION_KEY`.
- The attestation secret is never written to an artifact, child environment, report, or
  ledger. Its derived key ID may be recorded.
- An unattested v1/v2 package remains readable and diagnostic, but a new promotion gate
  evaluation cannot pass it.
- Live trading remains technically locked.

## 3. Workstream W1: Transactional Workflow State

### Deliverables

- Add a secure per-state advisory lock beside `state.yaml`.
- Run each driver against a uniquely named proposal file beside canonical state.
- Preserve the canonical state byte-for-byte on timeout, malformed output, illegal
  transition, evidence failure, or non-zero invalid exit.
- Validate the proposal against the pre-cycle state and policy before commit.
- Re-read canonical state immediately before commit and reject a changed source
  fingerprint.
- Atomically commit the candidate only after all checks pass.
- Delete proposal files on success and failure.
- Scope external dispatch locks by normalized workspace fingerprint while retaining the
  runtime-depth recursion guard.

### Acceptance Tests

- A two-transition counter jump leaves canonical state unchanged.
- A malformed state leaves canonical state unchanged.
- A timeout after a partial proposal leaves canonical state unchanged.
- Two supervisors for one state cannot execute concurrently.
- Two independent workspaces may dispatch concurrently.
- A nested dispatch in the same delegation chain remains forbidden.
- Existing valid supervisor, gate, waiting, blocked, and killed flows remain unchanged.

### Kill Conditions

- Any code path still gives a child the canonical state path.
- Any failed cycle can alter canonical state or consume transition/remediation budget.
- Lock cleanup requires deleting lock files manually.

## 4. Workstream D2: Resumable Dataset Acquisition

### Artifacts

- `dataset_plan.v1`: provider, instrument, event kind, requested interval, chunk interval,
  deterministic requests, cross-check policy, and plan fingerprint.
- `dataset_receipt.v1`: plan fingerprint, chunk receipts, aggregate event fingerprint,
  quality fingerprint, cross-check status, promotion impact, and commit fingerprint.
- Each chunk remains a standard immutable ingest bundle.

### Runtime

- Add a provider-neutral planner that partitions `[start_ns, end_ns)` without overlap.
- Add a resumable builder that skips only chunks whose request and receipt fingerprints
  still match the plan.
- Quarantine duplicate canonical identities with conflicting payloads.
- Deterministically merge and sort canonical events.
- Build aggregate quality and manifest evidence over the requested interval.
- Publish the dataset with staging plus atomic `COMMITTED`; never silently replace a
  committed dataset.
- Expose `the-pass data plan` and `the-pass data build` with stable JSON envelopes.
- Network use remains explicit through `--network`; offline fixture builds remain the CI
  default.

### Acceptance Tests

- Planning covers the exact interval with non-overlapping chunks.
- Interrupted builds resume without refetching valid committed chunks.
- Altered chunk requests or receipts fail closed.
- Duplicate identical events deduplicate deterministically.
- Conflicting duplicate events block publication.
- Missing required cross-check evidence produces a valid diagnostic dataset with blocked
  promotion impact.
- Two clean builds produce identical aggregate fingerprints.

## 5. Workstream A2: Generic Clean Reproduction

### Artifact And Runtime

- Add `reproduction_spec.v1` with a fixed runner ID, relative input paths, SHA-256 input
  fingerprints, expected output paths, and network policy.
- Custom `backtest run` packages copy canonical events, descriptor, execution config, and
  the declared strategy source into `reproduction/` before ledger recording.
- Add `the-pass audit reproduce <package>`.
- The reproducer creates a clean temporary workspace, verifies every input fingerprint,
  invokes only the allowlisted internal runner, validates the rebuilt package structure,
  and compares semantic artifact fingerprints.
- Baseline reproduction becomes a specialization of the same report contract.

### Acceptance Tests

- A custom strategy reproduces in a clean temporary directory.
- Input tampering blocks before execution.
- Unknown runner IDs and absolute/traversal paths are rejected.
- A semantic output mismatch produces `blocked` and exit `2`.
- The reproducer never invokes `shell=True` and receives no credentials or network by
  default.

## 6. Workstream G2: Reviewer Attestation

### Artifact

- Add `reviewer_attestation.v1` containing gate ID, exact package ID, reviewer, principal
  type, provider/model/run provenance, author provider, evidence fingerprints, key ID,
  and signature.
- The signature covers every field except `signature` using canonical JSON.
- The key ID is derived from the signing key; the key itself is never serialized.

### Enforcement

- The supervisor creates an attestation after a valid automated independent-review stage
  and before committing the transition to its gate stage.
- The signing key is removed from every child environment.
- Add `the-pass gate attest` for an explicit human or externally orchestrated review.
- `gate evaluate` requires a valid matching attestation before returning `pass` for
  `research_gate`, `paper_gate`, or `risk_review`.
- Automated attestations require reviewer provider != author provider.
- The gate decision fingerprints the attestation.
- Missing, malformed, mismatched, tampered, or unverifiable attestations return a valid
  blocked result with exit `2`.

### Acceptance Tests

- A different reviewer alias without an attestation cannot pass.
- One-byte attestation tampering cannot pass.
- A wrong package, gate, reviewer, key, provider separation, or evidence hash cannot pass.
- A valid supervisor-created attestation passes and is included in gate evidence.
- The signing key does not appear in state, reports, stdout/stderr evidence, or child env.
- Historical decisions remain ledger-readable.

## 7. Documentation And Compatibility

- Update README, Getting Started, Usage Guide, CLI contracts, artifact lifecycle, and
  changelog.
- Existing commands retain their current behavior except that new gate passes require an
  attestation.
- Existing single-bundle `data ingest` remains supported; `data plan/build` is additive.
- Existing baseline packages remain reproducible and ledger-readable.
- New custom run packages use the reproduction artifact automatically.

## 8. Verification Matrix

- Unit: proposal commit, locks, chunk planner, resume, signatures, path safety.
- Property/boundary: interval partitions, duplicate identities, source fingerprints,
  compare-and-swap conflicts.
- Mutation: state jump, malformed proposal, chunk tampering, forged reviewer, altered
  signature, changed reproduction input.
- End-to-end: data plan -> interrupted build -> resume -> backtest -> clean reproduce ->
  independent review -> attested gate decision.
- Compatibility: v1/v2 packages and ledgers remain readable.
- Safety: secret scan, child environment capture, no shell runner, no live imports, default
  tests offline.
- CI: Python 3.9 and 3.12, lock verification, lint, public validator, complete tests,
  package build, installed-wheel smoke.

## 9. Definition Of Done

The work is complete only when:

- all three audit reproductions have regression tests;
- all new artifacts validate through the schema registry;
- local lint, public validation, and the complete test suite pass;
- GitHub CI passes on Python 3.9 and 3.12;
- documentation contains no contradictory legacy gate or data instructions;
- no secret, credential, live client, or order transport is introduced;
- the implementation is merged into `main` and `main` is clean and synchronized.

## 10. Implementation Evidence

Implemented on `codex/harden-workflow-reproduction-attestation` for release `0.12.0`:

- W1: proposal-only child state, per-state commit lock, optimistic canonical fingerprint, and
  workspace-scoped external dispatch lock.
- D2: `dataset_plan`/`dataset_receipt`, resumable immutable chunks, aggregate deduplication,
  output-scoped build lock, and full committed-dataset revalidation.
- A2: bundled custom-run inputs, fixed allowlisted runner, clean temporary workspace, exact
  workspace allowlist, safe paths, and artifact fingerprint comparison.
- G2: HMAC-SHA256 reviewer attestations, parent-only key handling, automated provider separation,
  manual CLI attestation, and gate enforcement.

The release audit and exact command results are recorded in
[`reports/RELEASE_AUDIT_0.12.0.md`](../../reports/RELEASE_AUDIT_0.12.0.md).
Published asset verification is recorded in
[`reports/POST_RELEASE_AUDIT_0.12.0.md`](../../reports/POST_RELEASE_AUDIT_0.12.0.md).

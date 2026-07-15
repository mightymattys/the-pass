# Trust Boundary Hardening Plan

Status: approved for implementation
Target release: `v0.13.0`
Scope: dataset provenance, executable-code isolation, reviewer identity, ledger replay

## 1. Objective

This release closes three trust gaps found in the full-repository audit:

1. A committed dataset must prove the exact raw, normalized, quality, and manifest evidence that
   produced it. Resuming a dataset must never accept a changed chunk artifact.
2. Code executed by an automated workflow must not mutate the caller worktree before its state
   transition is validated. Strategy-runtime metadata must describe enforced isolation, not infer it
   from a module denylist.
3. A gate decision must remain verifiable without a secret environment variable. Reviewer evidence
   must use an asymmetric signature tied to a versioned public-key identity record.

The release remains engine-neutral, offline by default, Python 3.9/3.12 compatible, and unable to
place live orders.

## 2. Locked Decisions

- Existing ingest bundles and HMAC attestations remain readable for compatibility, but legacy
  reviewer attestations cannot authorize a new gate pass.
- New reviewer attestations use Ed25519. Private keys never enter artifacts, child environments,
  reports, or ledgers.
- Every v2 attestation embeds the signing public key and a registry record binding its fingerprint
  to the exact reviewer, principal type, provider, and validity interval. The registry record is
  copied into the attestation so historical verification needs only public evidence.
- Gate and ledger verification never read an attestation secret.
- Automated workflow agents run against a detached Git worktree. A validated patch is applied by
  the parent only after the proposed workflow transition passes all checks.
- Automatic agent execution snapshots the exact caller worktree, including uncommitted evidence,
  and refuses to apply any changed path whose caller-side fingerprint moved during execution.
  Trusted custom drivers retain their documented direct-workspace behavior and are never described
  as isolated.
- The strategy runtime exposes `trusted_local` and `hardened` trust modes. `trusted_local` is the
  portable default and is always diagnostic. `hardened` requires an explicit external sandbox
  launcher contract and fails closed when the launcher is unavailable.
- Import filtering is defense in depth, not proof of network denial. Runtime artifacts record the
  actual enforcement method and promotion eligibility.
- Live order transport remains absent and locked.

## 3. Workstream D1: Complete Dataset Provenance

### Implementation

- Add one authoritative ingest-bundle validator used by one-shot ingest, chunk resume, and
  committed-dataset replay.
- Require and parse `request.json`, `raw/response.json`, `canonical-events.jsonl`,
  `quality-report.json`, `data-manifest.json`, `ingest-receipt.json`, and `COMMITTED`.
- Recompute every fingerprint stored in the ingest receipt and validate event count, adapter
  identity, schema validity, manifest paths, and commit marker.
- Bind each aggregate dataset chunk row to a complete `bundle_fingerprint` derived from all chunk
  artifact fingerprints.
- Version dataset receipts to v2 while retaining read-only validation of v1 datasets.
- Never rewrite or repair a committed chunk. Any mismatch fails closed with the exact artifact
  named in the error.

### Acceptance tests

- Mutating each required chunk artifact independently blocks resume.
- Removing a required chunk artifact blocks resume.
- Two clean builds produce identical semantic fingerprints.
- An interrupted build resumes only untouched committed chunks.
- Existing v1 fixtures remain readable but cannot silently acquire v2 provenance claims.

## 4. Workstream E1: Transactional Execution Boundaries

### Automated workflow agents

- Resolve and require the Git repository root for `--driver auto` agent stages.
- Snapshot the exact caller worktree before dispatch and include its uncommitted files in the
  isolated copy without altering them. Local virtual environments, caches, and build outputs are
  excluded; any other symlink blocks dispatch before model execution.
- Create a detached temporary worktree at the caller's exact `HEAD`.
- Place the proposal state inside the worktree and remap repository-rooted paths between caller and
  isolated state documents.
- After execution, validate the remapped transition and all workflow evidence before accepting any
  files.
- Reject changes to protected state, ledger, gate decisions, Git metadata, and files outside the
  stage's declared evidence scope.
- Build a binary Git patch including untracked files. Check it against the unchanged caller tree,
  apply it, and only then atomically commit canonical workflow state.
- Remove the temporary worktree on success, timeout, malformed output, invalid transition, patch
  rejection, and interruption.
- Record worktree mode, patch hash, and changed paths in the supervisor report.

### Strategy runtime

- Add a versioned runtime isolation descriptor to worker results and reproduction evidence.
- `trusted_local` records process separation, stripped credentials, import filtering, and unrestricted
  host filesystem/network enforcement truthfully.
- `hardened` invokes an explicitly configured launcher with fixed placeholders for read-only input,
  writable output, and the worker argv. The launcher configuration is fingerprinted.
- Hardened results require an attestation file written by the launcher declaring no network,
  read-only workspace, writable temporary output only, and enforced resource boundaries.
- Missing, malformed, or mismatched launcher evidence is a safety failure.
- Promotion policy accepts only hardened evidence; trusted-local results remain useful for screens,
  diagnostics, and package construction with a blocked verdict.

### Acceptance tests

- A malformed, timed-out, or rejected agent cycle leaves both canonical state and caller worktree
  unchanged.
- A valid cycle applies exactly its allowed patch and state transition.
- Caller changes made during execution cause patch commit to fail closed.
- A source symlink cannot escape the isolated workspace and blocks before the driver starts.
- Trusted-local strategy code can demonstrate host access, and the report explicitly says that host
  filesystem/network are not OS-enforced.
- Hardened mode fails when no launcher exists and passes only with matching launcher evidence.

## 5. Workstream G1: Publicly Verifiable Reviewer Identity

### Artifact model

- Add `reviewer_key_registry.v1` and `reviewer_attestation.v2` schemas.
- Registry entries contain reviewer, principal type, provider, public key, key ID, validity interval,
  and optional revocation time.
- Key IDs are SHA-256 fingerprints of canonical raw Ed25519 public keys.
- Attestations contain the matching public registry entry, signature algorithm, signed evidence,
  and Ed25519 signature.
- Signing accepts a raw 32-byte private key encoded as base64 from
  `THE_PASS_REVIEW_SIGNING_KEY`; generation is an explicit CLI command and writes private material
  create-only with mode `0600`.

### Gate and ledger semantics

- New gate passes require schema v2 attestations.
- Verification checks signature, key fingerprint, reviewer/provider binding, validity at
  `created_at`, revocation, exact package/gate/evidence binding, and provider separation.
- Ledger replay verifies the embedded public evidence and never reads a secret.
- HMAC v1 remains structurally readable and produces a clear legacy/non-promotional blocker.
- The supervisor no longer fabricates a reviewer signature from a parent-wide shared secret.
  Automated review stops at a valid waiting checkpoint until the designated reviewer signs the
  completed review evidence or an externally signed v2 attestation already exists.

### Acceptance tests

- A v2 attestation verifies with an empty environment.
- Ledger replay remains valid after the signing key is removed or rotated.
- Wrong reviewer, provider, package, gate, public key, signature, validity interval, or revoked key
  blocks promotion.
- A v1 attestation validates as legacy evidence but cannot pass a new gate.
- Private key bytes never occur in package, report, ledger, child environment, or command output.

## 6. Compatibility And Migration

- Additive schema registry changes preserve all existing v1 readers.
- Dataset v1 validation retains its historical contract; new builds emit v2 and receive complete
  bundle validation.
- Reviewer v1 files remain parseable. A migration command is intentionally not provided because a
  new independent signature must be produced by the reviewer.
- Existing CLI groups and JSON envelopes remain stable. New commands and flags are additive.
- Documentation clearly distinguishes diagnostic execution, OS-enforced execution, evidence
  integrity, and identity trust.

## 7. Verification Matrix

- Unit: bundle validator, worktree lifecycle, patch transaction, path remapping, runtime-mode parser,
  Ed25519 signing and verification, key validity, CLI envelopes.
- Mutation: every committed chunk file, malformed sandbox attestation, patch scope escape, forged
  reviewer identity, changed public key, removed signing secret during ledger replay.
- End-to-end: ingest plan to committed dataset; custom strategy to blocked package; independent v2
  review to gate decision to secret-free ledger replay.
- Safety: secret scan, live-order import scan, no network in default CI, no credential inheritance.
- Distribution: Python 3.9 and 3.12, Ruff, public validator, wheel/sdist build, clean-wheel CLI and
  schema validation.

## 8. Release Gate

`v0.13.0` may be published only when:

- every acceptance test above passes;
- the original three audit reproductions now fail closed or report the boundary truthfully;
- all existing tests remain green;
- documentation, roadmap status, changelog, release notes, and release audit agree;
- no P0/P1 finding remains open in the release scope;
- required GitHub checks pass on the pull request;
- the reviewed commit is merged to `main`, tagged, published by the release workflow, and verified
  from downloaded release assets.

## 9. Implementation Record

Implemented for `v0.13.0` on 2026-07-15. The source matrix contains 241 tests and passes on Python
3.9 and 3.12. Ruff, lock validation, all milestone validators, fixture ingest through clean
reproduction and ledger replay, strict Claude plugin validation, wheel/sdist build, and clean-wheel
installation pass. Every acceptance item in Sections 3-5 has direct regression coverage.

The release commit, pull request, CI runs, tag workflow, asset hashes, and downloaded-wheel check
are recorded in `reports/RELEASE_AUDIT_0.13.0.md` and
`reports/POST_RELEASE_AUDIT_0.13.0.md` as those immutable GitHub identifiers become available. The
remaining compatibility limitations are explicit: v1 artifacts are historical, trusted-local code
is non-promotional, an OS sandbox launcher is operator-supplied, public-key registry approval stays
an organizational responsibility, and live transport remains absent.

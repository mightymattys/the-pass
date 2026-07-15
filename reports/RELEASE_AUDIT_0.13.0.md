# The Pass v0.13.0 Release Audit

Audit date: 2026-07-15
Scope: dataset provenance, auto-agent transaction isolation, runtime isolation truth, and reviewer
identity
Result: implementation complete and locally verified; GitHub evidence is recorded before
publication

## Implemented Controls

| Control | Result | Evidence |
| --- | --- | --- |
| Complete dataset provenance | pass | authoritative bundle validator, dataset receipt v2, per-artifact mutation tests |
| Transactional auto-agent workspaces | pass | detached worktree, scope validation, caller snapshot guard, atomic patch/state commit |
| Truthful strategy isolation | pass | explicit trusted/hardened modes, launcher hash and attestation, reproduction spec v2 |
| Public reviewer verification | pass | Ed25519 attestation v2, public registry snapshot, validity/revocation/provider checks |
| Symlink escape prevention | pass | source scan before dispatch; local environment/cache exclusions; driver-not-called regression |
| Compatibility | pass | v1 dataset/reproduction evidence readable; v1 HMAC evidence blocked from new promotion |
| Live safety boundary | pass | no credential loader, authenticated order client, or real order transport added |

## Acceptance Evidence

- Every required committed chunk artifact is independently mutation-tested.
- Failed and malformed automated agent cycles preserve the caller worktree and canonical state.
- A valid agent cycle applies exactly the declared evidence patch.
- Trusted-local runtime reports no OS network or filesystem enforcement.
- Hardened runtime fails without a launcher and accepts only exact launcher evidence.
- A v2 gate decision and full ledger replay verify after the signing key is removed.
- Wrong, expired, revoked, mismatched, tampered, or legacy reviewer evidence cannot pass.

## Local Verification

| Check | Result |
| --- | --- |
| `uv lock --check` | pass |
| `uv run ruff check .` | pass |
| `uv run python -m unittest discover -s tests -v` | pass, 241 tests |
| `uv run python scripts/validate_public_repo.py` | pass; all milestone validators green |
| Python 3.9 clean project matrix | pass, 241 tests and public validation |
| Python 3.12 project matrix | pass, 241 tests and public validation |
| `uv build` | pass; wheel and source distribution built |
| `scripts/validate_distribution.py` | pass; wheel contents and clean installed CLI |
| fixture ingest -> custom backtest -> clean reproduce -> ledger | pass; reproduction spec v2 reports truthful trusted-local isolation |
| Claude plugin and marketplace strict validation | pass |

Pull-request checks, merge commit, tag workflow, release assets, and downloaded-asset verification
are appended to the versioned post-release audit. They cannot be claimed before GitHub completes
those operations.

## GitHub Pull Request Gate

[PR #23](https://github.com/mightymattys/the-pass/pull/23) validated release commit `1e4af63` in
[CI run 29408107493](https://github.com/mightymattys/the-pass/actions/runs/29408107493). Required
checks `validate (3.9)` and `validate (3.12)` both passed. Branch protection also requires an
external approving review, and no independent GitHub approval was recorded. The repository owner
explicitly instructed this task to implement, verify, and deploy the release; as permitted by the
documented release process, an administrative merge exception may be used only after the updated
audit commit passes the same two required checks. The exception does not replace or bypass CI.

## Residual Boundaries

- The repository cannot supply a portable OS sandbox. Operators must audit and configure a launcher
  appropriate to their operating system before claiming hardened execution.
- A public key registry proves signature control and declared key binding. Organizations remain
  responsible for approving and distributing reviewer identity records.
- Public bars can support diagnostics but cannot prove fill-sensitive execution quality.
- Candidate strategy profitability is intentionally outside the framework release definition.

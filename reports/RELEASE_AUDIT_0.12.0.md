# The Pass v0.12.0 Release Audit

Audit date: 2026-07-15
Scope: post-audit workflow, dataset, reproduction, and reviewer-authority hardening
Result: locally verified; GitHub pull-request CI verified

## Implemented Controls

| Control | Result | Evidence |
| --- | --- | --- |
| Transactional workflow state | pass | proposal-only child path, per-state lock, compare-before-commit, canonical-preservation tests |
| Workspace dispatch concurrency | pass | workspace-derived dispatch lock and independent-workspace regression |
| Resumable dataset acquisition | pass | deterministic plan, committed chunks, aggregate receipt, full resume revalidation |
| Generic clean reproduction | pass | fixed runner, safe paths, exact workspace allowlist, input/output fingerprints |
| Reviewer authority | pass | signed attestation, independent provider check, gate binding, key non-disclosure test |
| Live safety boundary | pass | no credential loader, authenticated order client, or real order transport added |

## Verification

| Check | Result |
| --- | --- |
| `uv run ruff check .` | pass |
| `uv run python -m unittest discover -s tests` | pass, 231 tests in final release run |
| `uv run python scripts/validate_public_repo.py` | pass; all milestone validators green |
| `uv build --out-dir dist` | pass; wheel and source distribution built |
| `scripts/validate_distribution.py` | pass; wheel contents and clean installed CLI |
| no-network ingest -> backtest -> reproduce -> validate smoke | pass; rebuilt package valid, zero mismatches |
| Python 3.9 and 3.12 GitHub CI | pass in PR #21 ([run 29403976261](https://github.com/mightymattys/the-pass/actions/runs/29403976261)) |

## Residual Boundaries

- Custom strategy code is trusted local code. Import restrictions, credential stripping, bounded
  subprocesses, deterministic replay, and clean reproduction reduce risk but are not an OS sandbox.
- HMAC attestation proves integrity and possession of the configured local key. Organizations that
  require named human identity should supply their own secret-management and identity boundary.
- Public provider data can support diagnostics; venue-specific promotion still depends on source,
  license, market-depth, and observation evidence.

## Release Gate

Tag and release only after the final verification table is green, the branch is merged to `main`,
GitHub CI passes on Python 3.9 and 3.12, and the release workflow publishes signed checksums.

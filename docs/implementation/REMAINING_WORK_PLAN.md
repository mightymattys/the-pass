# The Pass Remaining Work Plan

Status: implementation complete; `v0.7.1` fix-forward publication authorized
Updated: 2026-07-10
Target release: `v0.7.1`

## 1. Purpose and Boundary

The Pass framework is feature-complete for its approved H0 through L5/L6 capability scope.
This plan contains only work that remains to make the public testing repository easier to
release, install, operate, and maintain. It does not require any strategy to be profitable or
to pass a candidate promotion gate.

Framework completion and candidate outcomes are independent:

- `framework_milestone: complete` means the repository can perform and audit the workflow.
- `candidate_gate_state: blocked|revise|kill|pass` is the result produced for one strategy.
- A correctly blocked or killed candidate proves that the testing system enforces its rules.
- Paper observation duration, licensed futures data, and live approval are user workflow
  inputs, not unfinished repository implementation.

Current baseline:

- The GitHub repository is public at `matk0shub/the-pass`.
- Commit `f9fb5e0` was the audited input baseline for this hardening cycle.
- RW0 through RW6 implementation and local acceptance checks are complete.
- `main` branch protection, required Python checks, review, and linear history are configured.
- CI tests both the checkout and the distributed wheel.
- Automation deadlines, staging, retry restrictions, incidents, and freeze evidence are
  enforced.
- Tag publication is delegated to the protected release workflow after merge.

## 2. Priority and Order

| ID | Priority | Workstream | Release blocking | Depends on |
| --- | --- | --- | --- | --- |
| RW0 | P0 | Freeze completion semantics | yes | none |
| RW1 | P0 | Enforce automation runtime contracts | yes | RW0 |
| RW2 | P0 | Distribution and CI hardening | yes | RW1 |
| RW3 | P1 | Public API and release documentation | yes | RW2 |
| RW4 | P1 | GitHub governance and `v0.7.1` release | yes | RW3 |
| RW5 | P1 | Maintenance and drift workflows | no | RW4 |
| RW6 | P2 | Performance and scale evidence | no | RW2 |

The mandatory release path is RW0 -> RW1 -> RW2 -> RW3 -> RW4. RW5 and RW6 improve
long-term reliability but do not reopen framework completion.

## 3. RW0: Freeze Completion Semantics

Owner: framework maintainer

Objective: make every public status surface distinguish repository capability from a tested
strategy's promotion result.

Inputs:

- `docs/implementation/roadmap-status.yaml`
- P4 and L5/L6 capability evidence
- candidate gate policies in `src/the_pass/gates.py`

Tasks:

1. Keep all H0-L5/L6 framework milestones `complete` with machine-readable capability gates.
2. Keep P4 and L5/L6 `candidate_gate_state: blocked` in public diagnostic evidence.
3. Require roadmap validation to reject disagreement between capability and candidate states.
4. Update README, master plan, completion audit, and final audit to use the same terminology.
5. Add mutation coverage for a fake P4 capability pass that omits candidate state, a candidate
   pass without evidence, and an L5/L6 capability record that enables live behavior.

Outputs:

- consistent roadmap and audit documents
- P4 and L5/L6 machine-readable capability gate records
- regression tests for state conflation

Acceptance:

- `scripts/validate_roadmap.py` passes for the tracked state
- each state-conflation mutation fails with a specific issue
- `scripts/validate_public_repo.py` passes
- no document describes a missing successful strategy as unfinished repository code

Stop condition: do not continue if any status field can imply candidate promotion from a
framework capability pass.

## 4. RW1: Enforce Automation Runtime Contracts

Owner: automation engineer

Objective: make `AutomationSpec.timeout_seconds`, retry rules, alert sink, and freeze procedure
operational rather than descriptive metadata.

Tasks:

1. Execute registered automation jobs in a cancellable child-process boundary.
2. Enforce `timeout_seconds`; terminate the child, preserve stdout/stderr evidence, and mark
   the run `failed` when the deadline expires.
3. Retry only commands listed as idempotent and only up to `max_attempts`.
4. Never retry `gate_checker`, `paper_observer`, or any future state-changing command.
5. Use a deterministic idempotency key across retries and scheduler restarts.
6. Write outputs to staging and expose them only after successful completion.
7. On terminal failure, create a schema-valid `IncidentReport`, record the alert sink and
   freeze action, and retain the last known-good output.
8. Ensure timeout, cancellation, or retry cannot leave a falsely `complete` receipt.

Required tests:

- executor completes before deadline
- executor exceeds deadline and is terminated
- retryable read fails once and succeeds once
- non-retryable command fails once with no second attempt
- partial staged output is not promoted
- duplicate scheduler invocation returns the original receipt
- terminal failure creates incident and freeze evidence

Acceptance:

- automation timeout is measured and enforced, not merely copied into a receipt
- every failure path produces a valid `AutomationRun`
- terminal failures produce a valid `IncidentReport`
- no retry path can call gate decision or live capability code
- all existing nine automation specs still validate

Kill condition: keep the current synchronous runner disabled for external jobs if a timed-out
executor cannot be reliably stopped.

## 5. RW2: Distribution and CI Hardening

Owner: release engineer

Objective: prove that users receive a working package, not only a working editable checkout.

CI changes:

1. Keep the Python 3.9 and 3.12 offline test matrix.
2. Add `uv lock --check` and `ruff check .`.
3. Build both sdist and wheel with `uv build`.
4. Install the wheel in a clean temporary environment outside the repository.
5. From that environment run:
   - `the-pass --version`
   - artifact validation using packaged schemas
   - a blocked diagnostic package validation
   - a receipt add/verify cycle
   - import checks for base, data, research, and paper modules
6. Inspect wheel contents for all schemas and policy files and for the absence of reports,
   licensed fixtures, credentials, and repository-only files.
7. Upload wheel, sdist, and validation logs as CI artifacts on tagged builds.
8. Keep network adapter smoke outside default CI and expose it only through manual or scheduled
   workflows.

Test hardening:

- parameterize the stable JSON envelope contract across every CLI group and common error path
- test roadmap gate mutations rather than only the valid tracked roadmap
- test schema lookup from an installed wheel with no repository root available
- verify clean replay fingerprints on both supported Python versions
- add a test that the public live-order scan also runs against wheel contents

Acceptance:

- source checkout tests pass on Python 3.9 and 3.12
- clean wheel tests pass on Python 3.9 and 3.12
- Ruff, lock validation, public validation, and package build are required CI checks
- wheel/sdist build without warnings
- default CI performs no network request

Kill condition: do not publish a release whose wheel requires fallback files from the source
repository.

## 6. RW3: Public API and Release Documentation

Owner: documentation maintainer

Objective: make the public contracts usable without reading implementation code or chat history.

Tasks:

1. Add `CHANGELOG.md` using Keep a Changelog sections and Semantic Versioning.
2. Add a release procedure covering version bump, generated evidence, tests, tag, GitHub
   release, rollback, and post-release verification.
3. Document the stable CLI JSON envelope and exit codes once, then link skills and command docs
   to that canonical contract.
4. Document schema compatibility: v1 read-only support, v2 generation, additive changes, and
   the process for a future breaking v3.
5. Add an installed-package quickstart that does not assume a repository checkout.
6. Add one minimal end-to-end example for each outcome: `pass`, `blocked`, `revise`, and `kill`.
   The pass example may exercise a framework capability gate; it must not fake strategy edge.
7. Update the public release checklist to record exact commands, supported Python versions,
   artifact hashes, CI URL, and reviewer.
8. Remove stale test counts or generate them from release evidence rather than duplicating them
   across reports.

Acceptance:

- all documentation links pass public validation
- no command contract is defined differently in README, skills, and CLI docs
- a new user can install the wheel and validate an example using only documented commands
- candidate and framework gate terminology remains explicit throughout

## 7. RW4: GitHub Governance and v0.7.1 Release

Owner: repository maintainer

Objective: turn the validated local state into a controlled public release.

Tasks:

1. Review the complete diff and split commits by concern: gate semantics, automation runtime,
   CI/distribution, and docs/release.
2. Push a `codex/release-hardening` branch and require a pull request review.
3. Protect `main` with required CI, no force-push, no deletion, and resolved review threads.
4. Add a pull-request template requiring scope, evidence, safety impact, and validation commands.
5. Add Dependabot updates for GitHub Actions and Python dependencies on a monthly cadence.
6. Version the release as `0.7.1`; update package version, changelog, audit, and release notes in
   one commit.
7. Create an annotated `v0.7.1` tag only after protected-branch CI passes.
8. Publish a GitHub Release with checksums and CI-built wheel/sdist artifacts.
9. Install the release artifact in a fresh environment and run the documented smoke workflow.
10. Keep PyPI publication out of scope until separately and explicitly approved.

Acceptance:

- working tree is clean and local `main` matches `origin/main`
- required protected-branch checks are green
- tag, changelog, package version, and GitHub release agree on `0.7.1`
- release assets match CI-generated checksums
- post-release installed-package smoke passes

Rollback: delete or mark the GitHub release as withdrawn, preserve the tag and failed evidence,
fix forward with a patch release, and never rewrite published history.

## 8. RW5: Maintenance and Drift Workflows

Owner: repository maintainer

Objective: detect dependency, provider, documentation, and fixture drift after release.

Tasks:

1. Add a weekly opt-in public adapter smoke workflow for Binance and Polymarket.
2. Archive smoke metadata, endpoint versions, timestamps, and failures without storing secrets.
3. Open or update one issue when a provider contract drifts; do not silently rewrite fixtures.
4. Add monthly dependency and GitHub Actions update pull requests.
5. Run a scheduled dependency vulnerability audit and public secret/live-path scan.
6. Add a corpus link/recency report that changes source status only after human review.
7. Define fixture refresh rules requiring old fixture retention or an explicit migration note.

Acceptance:

- scheduled failures create actionable evidence without changing promotion state
- provider drift cannot modify golden results automatically
- dependency updates execute the full offline CI matrix
- licensed or authenticated providers are never contacted by public automation

## 9. RW6: Performance and Scale Evidence

Priority: optional, non-blocking

Owner: performance maintainer

Objective: detect regressions in the testing tool itself without claiming strategy performance.

Tasks:

1. Add deterministic benchmark generators for canonical events, Parquet partitions, and replay.
2. Measure event normalization, quality checks, feature generation, simulator replay, ledger
   verification, and dashboard build time.
3. Record peak memory and throughput for fixed 10k, 100k, and 1m-event fixtures.
4. Establish regression budgets from the first tagged baseline rather than inventing absolute
   hardware-independent speed claims.
5. Run small benchmarks in CI and larger benchmarks on a scheduled runner.
6. Optimize only after a measured regression or user-relevant bottleneck is demonstrated.

Acceptance:

- benchmark inputs and seeds are reproducible
- reports identify machine and dependency versions
- performance changes cannot alter artifact fingerprints or accounting results
- no benchmark is interpreted as evidence of strategy profitability

## 10. Explicitly Out of Scope for Repository Completion

The following are activities performed with The Pass, not remaining implementation work:

- discovering a profitable strategy
- completing a 30-day or 60-day candidate observation window
- collecting candidate fill or signal minimums
- purchasing or providing licensed futures data
- obtaining venue credentials
- implementing or enabling real order transport
- passing a candidate research, paper, risk, or live gate
- publishing to PyPI

These items may create evidence consumed by the repository, but none is required to call the
testing framework complete.

## 11. Final Definition of Done

Mandatory remaining work is complete when:

- RW0 through RW4 acceptance criteria pass
- automation deadlines and terminal failures are enforced and audited
- checkout and installed-wheel tests pass on Python 3.9 and 3.12
- public validation, Ruff, lock check, wheel, and sdist checks are required in CI
- branch protection is active and the release was merged through review
- `v0.7.1` has matching code, tag, changelog, checksums, and GitHub release assets
- the repository is clean, public, secret-free, and contains no live order path
- candidate outcomes remain independent from framework completion

RW5 and RW6 remain ongoing maintenance tracks after the release.

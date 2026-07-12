# The Pass v0.7.0 Release Audit

Audit date: 2026-07-10
Audit verdict: superseded by `v0.7.1`
Open P0/P1 findings: none
Candidate promotion claim: none
Live capability: locked

## Scope

This audit evaluates repository capability, distribution safety, automation failure behavior,
maintenance controls, and framework efficiency. It does not evaluate a trading strategy.

## Closed Findings

1. Framework milestone passes and candidate gate states are independently represented and
   protected by roadmap mutation tests.
2. Automation deadlines are enforced in cancellable child processes. Outputs remain staged
   until success; terminal failures preserve logs and create incident/freeze evidence.
3. CI validates the lock file, Ruff, public safety, 101 tests, wheel/sdist builds, and a clean
   installed-wheel workflow on Python 3.9 and 3.12.
4. The wheel contains all schemas and policies, no repository-only reports or fixtures, and no
   live-order or credential-loading path.
5. Public maintenance workflows are network opt-in and cannot mutate fixtures, research review
   status, or candidate promotion state.
6. Feature generation no longer creates a duplicate canonical row tree. Parquet commits stream
   10k-row batches while preserving the original deterministic fingerprint algorithm.

## Verification Evidence

- Python 3.9: 101 tests passed.
- Python 3.12: 101 tests passed.
- `scripts/validate_public_repo.py`: passed.
- `scripts/validate_distribution.py`: passed against `the_pass-0.7.0-py3-none-any.whl`.
- Ruff and `uv lock --check`: passed.
- Plugin validator and all 11 slash-skill validators: passed in the release workspace.
- Dependency audit: no known vulnerabilities in resolved third-party packages.
- Public read-only adapter smoke: passed for Binance, Polymarket, and the futures fixture.
- Research link report: 50 sources checked with zero provider/network errors; restricted pages
  remain classified without changing review status.

## Scale Evidence

The deterministic benchmark completed 10k, 100k, and 1m canonical-event runs. The 1m run
completed quality, features, replay, Parquet commit, ledger verification, and dashboard build.
Peak Python-managed memory decreased from approximately 3.16 GB in the initial audit run to
1.93 GB after chunking and duplicate-copy removal. Exact machine and dependency evidence is in
`reports/benchmarks/baseline-v0.7.0.json`.

## Governance

- Protected review: `https://github.com/mightymattys/the-pass/pull/1`.
- Cross-version CI evidence: `https://github.com/mightymattys/the-pass/actions/runs/29074681353`.
- `main` requires the Python 3.9 and 3.12 CI checks.
- Pull-request review, linear history, resolved conversations, and strict up-to-date checks are
  required.
- Force pushes and branch deletion are disabled.
- Dependabot covers Python and GitHub Actions monthly.
- Tag publication runs an independent two-version validation before creating the GitHub Release.

## Safety Result

The release contains no authenticated venue channel, credentials, real order transport, paid
data, or private account evidence. Framework capability is complete while diagnostic
`paper_gate` and public `live_gate` remain blocked. A killed or blocked candidate remains a
successful output of the testing system.

## Release Authorization

The repository is authorized for the annotated `v0.7.0` tag after protected-branch CI and pull
request review pass. The tag workflow must build the release artifacts, verify their installed
behavior, publish SHA-256 checksums, and attach this report. Failure of any workflow step blocks
publication without changing prior evidence.

## Post-release Finding

The artifact digests were correct, but `SHA256SUMS` stored `dist/` path prefixes that are not
present after GitHub asset download. The release is preserved as evidence and superseded by
the fix-forward `v0.7.1` release.

# The Pass v0.9.1 Release Audit

Audit date: 2026-07-10

Candidate verdict: **PASS FOR RELEASE UNDER EXPLICIT OWNER EXCEPTION**

Publication state: [PR #11](https://github.com/mightymattys/the-pass/pull/11) passed both required
contexts in [CI run 29111305599](https://github.com/mightymattys/the-pass/actions/runs/29111305599)
and was administratively merged as `ff98ac4` under the documented owner exception. Publication
still requires the annotated tag, release workflow, and downloaded-asset verification.

## Why A Patch Release Is Required

The `v0.9.0` code and tests were stable, but a clean user installation audit found two public
plugin distribution defects:

1. Codex detected the repository as a marketplace but listed no available plugin because the
   repository lacked `.agents/plugins/marketplace.json`.
2. Claude accepted its marketplace but the `github` source attempted an SSH clone, making clean
   installation fail without a configured GitHub key.

Both defects affect how users reach the already tested functionality, so they are fixed in a
versioned patch rather than documented as manual workarounds.

## Review Exception

The repository requires one approving review but has no second collaborator. The owner previously
instructed the agent to complete versioned releases after being informed that the administrative
exception must be explicit and documented. This exception applies to `v0.9.1`; both required
Python contexts and every technical release gate remain mandatory.

## Verified Result

- Package, Codex plugin, Claude plugin, both marketplaces, skill policy, and agent policy agree on
  `0.9.1`.
- Clean isolated Codex and Claude profiles both install and enable `the-pass@the-pass-tools`
  through the remote Git branch without user settings, SSH keys, or cache reuse. Each installed
  archive contains exactly seven skills and four bounded Claude agent definitions.
- The documented CLI smoke validates a synthetic package, appends and verifies a ledger, creates
  workflow state, builds a seeded-random package, and validates that package.
- All 37 latest-version templates pass production artifact validation.
- Ruff, public validation, plugin validators, distribution validation, and all 172 tests pass.
- No live order path, credential loader, authenticated venue channel, or new gate authority is
  introduced.

## Release Inputs

- Changelog: `CHANGELOG.md`
- Usage guide: `docs/public/USAGE_GUIDE.md`
- Release notes: `docs/public/RELEASE_NOTES_v0.9.1.md`
- Codex marketplace: `.agents/plugins/marketplace.json`
- Codex manifest: `.codex-plugin/plugin.json`
- Claude marketplace: `.claude-plugin/marketplace.json`
- Package metadata: `pyproject.toml`

## Publication Gates

- [x] Local release and installation matrix passes.
- [x] Release PR passes Python 3.9 and 3.12.
- [x] Administrative review exception is documented.
- [x] Release PR is merged as `ff98ac4` and the commit is recorded.
- [ ] Annotated `v0.9.1` tag triggers the release workflow.
- [ ] Wheel, sdist, checksums, and audit are published.
- [ ] Fresh downloads pass checksum and clean-install verification.

Until all remaining gates complete, `0.9.1` is a validated release candidate, not a published
release.

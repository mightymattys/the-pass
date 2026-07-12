# The Pass v0.10.0 Release Audit

Audit date: 2026-07-12

Candidate verdict: **PASS FOR RELEASE UNDER EXPLICIT OWNER EXCEPTION**

Publication state: [PR #13](https://github.com/mightymattys/the-pass/pull/13) passed both required
contexts before merge and the resulting `main` commit `0c5dfca` passed both contexts in
[CI run 29206394137](https://github.com/mightymattys/the-pass/actions/runs/29206394137). The owner
explicitly instructed the agent to complete the merge. Publication still requires the release
preparation commit, annotated tag, release workflow, and downloaded-asset verification.

## Release Scope

Version `0.10.0` adds supervised end-to-end workflow execution and policy-controlled routing
between current Codex and Claude model catalogs. It also hardens accounting, evidence durability,
review independence, data chronology, paper isolation, and risk enforcement.

The release does not add a live order transport, credential loader, authenticated venue channel,
or model authority over deterministic gates.

## Review Exception

The protected branch requires one approving review and does not enforce that rule for repository
administrators. No independent collaborator approval was available. The owner explicitly directed
the agent to complete the repository after being informed of that blocker. Both required Python
contexts, all deterministic validators, and the local release matrix remained mandatory.

## Verified Result

- Package, Codex plugin, Claude plugin, marketplaces, and orchestration policies agree on version
  `0.10.0`.
- Codex routing rejects every model older than GPT-5.6 and the policy requires exactly two or three
  reviewed current models per provider.
- The supervised workflow cannot report completion after timeout, no progress, illegal state
  transition, invalid evidence, failed gate, or exhausted budget.
- Independent review stages fail closed when provider separation cannot be established.
- Public validation passes all roadmap, research corpus, data, B2, V3, and P4 checks.
- Ruff passes; all 197 tests pass; wheel and source distribution build successfully.
- Python 3.9 and 3.12 pass the complete GitHub validation matrix on the merged source commit.

## Release Inputs

- Changelog: `CHANGELOG.md`
- Usage guide: `docs/public/USAGE_GUIDE.md`
- Release notes: `docs/public/RELEASE_NOTES_v0.10.0.md`
- Supervised workflow audit: `reports/SUPERVISED_WORKFLOW_AUDIT_2026-07-11.md`
- Repository hardening audit: `reports/REPOSITORY_HARDENING_AUDIT_2026-07-10.md`
- Package metadata: `pyproject.toml`

## Publication Gates

- [x] Local release and installation matrix passes.
- [x] Source PR and merged `main` pass Python 3.9 and 3.12.
- [x] Administrative review exception is documented.
- [x] Release audit, notes, changelog, and checklist are present and version-aligned.
- [ ] Release preparation commit passes protected CI and is merged.
- [ ] Annotated `v0.10.0` tag triggers the release workflow.
- [ ] Wheel, sdist, checksums, and release audit are published.
- [ ] Fresh downloads pass checksum and clean-install verification.

Until all remaining gates complete, `0.10.0` is a validated release candidate, not a published
release.

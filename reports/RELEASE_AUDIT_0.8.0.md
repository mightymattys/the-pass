# The Pass v0.8.0 Release Audit

Audit date: 2026-07-10

Post-publication note: the release completed successfully after this candidate audit was attached
to the tag. Downloaded assets and checksums were reverified in
[POST_RELEASE_AUDIT_0.8.0.md](POST_RELEASE_AUDIT_0.8.0.md).

Candidate verdict: **PASS FOR RELEASE UNDER EXPLICIT OWNER EXCEPTION**

Publication state: PR #6 was administratively squash-merged as commit `0944d60` after both
required CI contexts passed. The sole repository collaborator explicitly instructed the agent to
perform the merge after being told that it would bypass the required independent approval. No
independent GitHub review was recorded. Publication still requires the annotated `v0.8.0` tag and
successful release workflow.

## Scope

This audit covers the `0.8.0` source package, Codex plugin, seven-skill interface, bounded
workflow, exact-package ledger/gate semantics, public safety boundary, documentation, and
installed distribution. It does not claim that a strategy is profitable or candidate-approved.

## Verified Result

- Package and plugin versions agree on `0.8.0`.
- The plugin exposes exactly seven skills and all seven pass the canonical skill validator.
- The plugin manifest passes the canonical plugin validator.
- Locked dependencies, Ruff, public repository validation, and distribution validation pass.
- Unit, contract, property, mutation, safety, and end-to-end suite: **143/143 pass**.
- Fresh isolated Python 3.9 and Python 3.12 suites pass.
- The installed wheel loads packaged schemas and policies outside the checkout.
- Exact-path v2 runs, run-before-gate order, unique package IDs, successor lineage, target-gate
  remediation evidence, and terminal workflow budgets have regression coverage.
- No open P0/P1 finding remains in the independent focused audit.

The detailed trust-boundary finding ledger is in
[SLASH_SKILL_CONSOLIDATION_AUDIT_2026-07-10.md](SLASH_SKILL_CONSOLIDATION_AUDIT_2026-07-10.md).

## Release Inputs

- Changelog: `CHANGELOG.md`
- Release notes: `docs/public/RELEASE_NOTES_v0.8.0.md`
- Completion audit: `docs/implementation/COMPLETION_AUDIT.md`
- Machine policy: `config/skill-pipeline.v1.yaml`
- Plugin manifest: `.codex-plugin/plugin.json`
- Package metadata: `pyproject.toml`

## Publication Gates

- [x] Protected pull-request CI passed on Python 3.9 and 3.12.
- [x] The owner explicitly authorized an administrative exception because no second collaborator
  was available; this substitutes for the GitHub approval requirement for this release only.
- [x] PR #6 was squash-merged to `main` as `0944d60`.
- [ ] An annotated `v0.8.0` tag triggers `.github/workflows/release.yml`.
- [ ] Release assets and `SHA256SUMS` are generated and validated by that workflow.

Until the final two gates complete, `0.8.0` is a validated release candidate, not a published
release.

## Safety Result

- No live order path or credential loader is present.
- Public adapter access is read-only and network tests remain opt-in.
- Paper execution is virtual and process-isolated.
- Gate decisions are separate from run receipts and bind exact evidence.
- Candidate gate state remains independent from framework capability completion.

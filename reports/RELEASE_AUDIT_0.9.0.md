# The Pass v0.9.0 Release Audit

Audit date: 2026-07-10

Candidate verdict: **PASS FOR RELEASE UNDER EXPLICIT OWNER EXCEPTION**

Publication state: release preparation is in progress. This record will be finalized with the
release pull request and merge commit before the annotated `v0.9.0` tag is created.

## Review Exception

The repository requires one approving review, but it has no second collaborator available for an
independent GitHub approval. The owner was told that completing the release would require either
an independent approval or an explicitly documented administrative exception and then instructed
the agent to finish the release. This authorization applies only to the `v0.9.0` release. It does
not weaken required Python 3.9/3.12 checks, technical validation, or future branch protection.

## Scope

This audit covers the `0.9.0` Python package, Codex and Claude Code plugins, shared seven-skill
interface, native Claude agents, cross-provider broker, capability-aware model routing, artifact
schemas and templates, distribution contents, documentation, and locked live boundary. It does
not approve a trading strategy, provider credential, model-generated patch, or live capability.

## Verified Result

- Package, Codex plugin, Claude plugin, marketplace, and packaged policy versions agree on
  `0.9.0`.
- The same seven skills validate for both plugin surfaces.
- The Codex plugin, all seven Codex skills, both strict Claude manifests, and four Claude agents
  validate.
- The complete offline unit, contract, mutation, safety, and end-to-end suite contains 172 passing
  tests.
- Locked dependencies, Ruff, public repository validation, source distribution, wheel, and clean
  installed-wheel validation pass.
- Every one of the 37 registered latest-version templates passes the production artifact
  validator and remains non-promoting.
- Fixture dispatch passes in both provider directions; real read-only Codex/Claude smoke evidence
  is recorded without workspace writes.
- Public Binance and Polymarket read-only adapter smoke and futures fixture replay pass.
- No open P0/P1 framework or orchestration finding remains.

Detailed evidence:

- [CROSS_AGENT_ORCHESTRATION_AUDIT_0.9.0.md](CROSS_AGENT_ORCHESTRATION_AUDIT_0.9.0.md)
- [FULL_REPOSITORY_STABILITY_AUDIT_2026-07-10.md](FULL_REPOSITORY_STABILITY_AUDIT_2026-07-10.md)
- [SLASH_SKILL_CONSOLIDATION_AUDIT_2026-07-10.md](SLASH_SKILL_CONSOLIDATION_AUDIT_2026-07-10.md)

## Release Inputs

- Changelog: `CHANGELOG.md`
- Release notes: `docs/public/RELEASE_NOTES_v0.9.0.md`
- Completion audit: `docs/implementation/COMPLETION_AUDIT.md`
- Model and orchestration policy: `config/agent-orchestration.v1.yaml`
- Skill pipeline policy: `config/skill-pipeline.v1.yaml`
- Codex manifest: `.codex-plugin/plugin.json`
- Claude manifests: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`
- Package metadata: `pyproject.toml`

## Publication Gates

- [x] Local release matrix passes.
- [ ] Release pull request passes both required Python contexts.
- [x] The owner explicitly authorized and required documentation of the administrative review
  exception because no second collaborator is available.
- [ ] Release pull request is merged to `main` and its commit is recorded here.
- [ ] Annotated `v0.9.0` tag triggers `.github/workflows/release.yml`.
- [ ] Release workflow validates Python 3.9/3.12 and publishes wheel, sdist, audit, and checksums.
- [ ] Freshly downloaded assets pass checksum and clean-install verification.

Until the remaining gates complete, `0.9.0` is a validated release candidate rather than a
published release.

## Safety Result

- No live order transport, authenticated venue client, or credential loader is present.
- Broker-managed agents cannot modify gate, ledger, policy, plugin, release, schema, security, or
  live-boundary authorities.
- Implementation tasks return an unapplied worktree patch; read-only tasks cannot write.
- External dispatch is explicit, serialized, bounded, non-recursive, and never retried silently.
- Candidate gate state remains independent from framework and release completion.

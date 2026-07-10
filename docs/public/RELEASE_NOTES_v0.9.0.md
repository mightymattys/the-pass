# The Pass v0.9.0

`v0.9.0` makes The Pass portable across Codex and Claude Code, adds bounded cross-provider agent
delegation, and closes the artifact-template validity gap found by the final repository audit.

## Highlights

- One shared set of seven `/the-pass:*` skills for Codex and Claude Code.
- Four finite Claude native agents: coordinator, researcher, implementer, and reviewer.
- Explicit `the-pass agents doctor`, `inspect`, and `dispatch --execute` commands.
- Capability-aware `economy`, `balanced`, and `deep` model routing for both providers.
- Read-only research/review delegation and isolated-worktree implementation proposals.
- Strict `AgentTask`, `AgentResult`, and `AgentRun` artifacts with model, policy, limit, and output
  fingerprints.
- Provider configuration isolation, serialized external dispatch, depth-one recursion control,
  bounded process groups, and no automatic patch application.
- All 37 latest-version artifact templates are now schema-valid, semantically checked, and
  deliberately non-promoting.

## Compatibility

- Python 3.9 and 3.12 remain supported.
- Existing v1 evidence remains readable but cannot authorize a v2 gate.
- The Python CLI and seven-skill interface are additive over `v0.8.0`.
- Default CI remains offline; authenticated agent and public adapter smokes are explicit and
  opt-in.

## Safety

Agent output is evidence input only. It cannot append gate decisions, approve live trading, apply
its own patch, commit, push, access venue credentials, or place an order. The public `live_gate`
remains technically locked.

See the [cross-agent audit](../../reports/CROSS_AGENT_ORCHESTRATION_AUDIT_0.9.0.md),
[full stability audit](../../reports/FULL_REPOSITORY_STABILITY_AUDIT_2026-07-10.md), and
[`v0.9.0` release audit](../../reports/RELEASE_AUDIT_0.9.0.md) for the complete verification and
residual boundaries.

# ADR-0010: Portable Agent Orchestration

Status: accepted

Date: 2026-07-10

Owner: automation_engineer

## Context

The Pass `0.8.0` exposes one Codex plugin and seven shared skills. Claude Code can consume the same
skill layout, but the repository lacked a Claude manifest, distributable marketplace, native
agent roles, and a deterministic boundary for asking one local agent CLI to review work produced
by the other.

Directly teaching each skill to shell out to an arbitrary model would duplicate provider logic,
weaken safety, and permit recursive Codex/Claude loops. Allowing a foreign agent to edit the
caller's workspace would also undermine immutable evidence and user-owned changes.

## Decision

The repository supports Codex and Claude Code from one shared `skills/` tree and two platform
manifests. Claude additionally receives four plugin agents: a main-session coordinator and three
non-recursive specialists.

Cross-provider execution uses the additive `the-pass agents` CLI and versioned
`AgentTask`, `AgentResult`, and `AgentRun` artifacts. The broker invokes only installed `codex` and
`claude` CLIs, requires explicit `--execute`, limits cross-provider depth to one, performs one
attempt, and records bounded output fingerprints.

Read-only tasks use provider-enforced read restrictions. Write tasks execute in a detached
temporary git worktree and return an unapplied patch. Gate, ledger, live-boundary, policy, plugin,
schema, release, and security authorities are protected from agent patches.

Agent findings are evidence inputs only. The broker cannot append gate decisions, approve live
trading, load credentials, commit, push, or apply a returned patch.

## Consequences

- Codex and Claude Code expose the same `/the-pass:*` skill vocabulary.
- Users can install the Claude plugin from a pinned repository marketplace release.
- Native subagents reduce context pressure without changing gate authority.
- Cross-provider work is opt-in, may consume the user's existing provider entitlement, and is not
  exercised by default CI.
- Proposed writes require a separate validation and acceptance step.
- Provider CLI drift is isolated in two command builders and fixture-tested offline.

## Alternatives Rejected

- Duplicate Claude skills: rejected because contracts would drift.
- Direct vendor APIs: rejected because they introduce credential handling and another runtime.
- Unrestricted shell prompts: rejected because they cannot enforce permissions or audit argv.
- Recursive agent teams across providers: rejected because cost and convergence are unbounded.
- Automatic patch application: rejected because a foreign agent must not mutate caller state.
- Treating agent review as gate passage: rejected because only exact-package gate evaluation is
  authoritative.

## Validation

- Official Codex and Claude plugin validators pass.
- Fixture dispatch succeeds Codex-to-Claude and Claude-to-Codex without network access.
- Recursion, timeout, output, objective, path, protected-authority, and worktree isolation tests
  fail closed.
- Python 3.9/3.12, wheel, public safety, secret, and live-order checks remain green.

## Review Trigger

Revisit when either provider removes the invoked CLI contract, a direct SDK becomes necessary for
streaming controls, or real usage proves depth one insufficient. Any deeper topology requires a
new ADR with explicit cost, recursion, and independence semantics.

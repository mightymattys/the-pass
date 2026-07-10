# Codex, Claude Code, and Agent Delegation

The Pass ships one shared set of seven skills for Codex and Claude Code. Native subagents and
cross-provider CLI delegation are separate capabilities: installing both plugins does not make a
model call, and `the-pass agents inspect` never executes a provider.

## Plugin Installation

### Codex

Use the repository's `.codex-plugin/plugin.json` through the normal Codex plugin installation
flow. The commands are namespaced as `/the-pass:run`, `/the-pass:research`, and the other five
shared skills.

### Claude Code development checkout

```bash
claude --plugin-dir /path/to/the-pass
```

Validate both the plugin and marketplace manifests:

```bash
claude plugin validate .claude-plugin/plugin.json --strict
claude plugin validate . --strict
```

### Claude Code pinned release

After `v0.9.0` is published:

```text
/plugin marketplace add matk0shub/the-pass
/plugin install the-pass@the-pass-tools
/reload-plugins
```

The seven skills appear under `/the-pass:*`. Claude also exposes the `coordinator`, `researcher`,
`implementer`, and `reviewer` plugin agents. The coordinator is a main-session role; specialists
cannot spawn another agent.

## Native Subagents

Prefer native subagents for self-contained context-heavy work:

- researcher: read-only source and repository investigation;
- reviewer: fresh read-only adversarial review;
- implementer: one isolated-worktree proposal;
- coordinator: main Claude session routing to those three roles.

The main agent validates every result. Native reviewer output is not a gate decision, and native
implementer changes are not accepted merely because the subagent finished.

## Cross-Provider Tasks

Start from [agent_task.yaml](../../templates/agent_task.yaml). Set caller and target to different
providers, resolve `workspace_root` relative to the task file, and keep every input/write path
repository-relative.

Offline capability and invocation checks:

```bash
the-pass agents doctor --provider all --format json
the-pass agents inspect path/to/agent-task.yaml --format json
```

`doctor` runs only each binary's `--version`; it does not check authentication or contact a
model. `inspect` validates limits, paths, roles, objective screening, and sanitized argv without
execution.

Explicit execution:

```bash
the-pass agents dispatch path/to/agent-task.yaml \
  --output-dir reports/agents --execute --format json
```

Execution uses the user's existing Codex or Claude CLI authentication and may incur usage or API
cost. The broker never reads or records credential values and does not forward direct API-key
environment variables; use the provider CLI's local authenticated configuration. It makes one
attempt, enforces the task's timeout/output/budget bounds, and records a create-only `AgentRun`.

Claude Code may return schema output in `structured_output`, as a raw result JSON string, or as one
JSON code fence inside the standard result envelope. The broker accepts only one unambiguous object
and applies the same schema, task identity, path, and evidence checks in every case.

Provider generation uses a deliberately small structured-output schema supported by both CLIs.
That schema is not evidence authority: the broker always revalidates the extracted object against
the stricter public `agent_result.schema.json` before it can complete.

## Write Isolation

`researcher` and `reviewer` tasks must use `read_only`. `implementer` tasks use
`worktree_patch` and declare narrow `allowed_write_paths`. The broker creates a unique detached
worktree from current `HEAD`, checks every changed path, emits `agent-patch-<run-id>.patch`, and
deletes the worktree. It never applies, stages, commits, or pushes the patch.

Caller uncommitted changes are not included in that worktree. Apply a returned patch only after
reviewing it and running the normal repository validation matrix.

## Safety and Authority

- Cross-provider depth is one; a delegated process cannot delegate back.
- Broker-managed Claude native delegation is read-only and may invoke only the `researcher` and
  `reviewer`; the full coordinator/implementer route is available only in a user-controlled native
  main session.
- Dangerous Codex/Claude permission bypass flags are forbidden.
- Claude read-only tasks receive only read/search tools; write tasks receive edit/write tools but
  no Bash or Agent tool.
- Codex uses `read-only` or isolated `workspace-write` sandbox mode.
- Gate, ledger, policy, plugin, release, schema, security, and live-boundary paths cannot be
  changed by broker-managed patches.
- Agent findings may inform normal review artifacts but cannot append or replace a
  `gate_decision`.
- No broker command places orders, authenticates to a venue, or unlocks `live_gate`.

Default CI uses fixture provider executables and makes no authenticated provider call. Real
cross-provider smoke tests are manual and opt-in.

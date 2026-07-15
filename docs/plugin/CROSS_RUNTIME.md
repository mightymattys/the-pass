# Codex, Claude Code, and Agent Delegation

The Pass ships one shared set of seven skills for Codex and Claude Code. Native subagents and
cross-provider CLI delegation are separate capabilities: installing both plugins does not make a
model call, and `the-pass agents inspect` never executes a provider.

## Plugin Installation

### Codex

Install the pinned repository marketplace and plugin:

```bash
codex plugin marketplace add mightymattys/the-pass --ref v0.12.0
codex plugin add the-pass@the-pass-tools
```

Start a new task after installation. The commands are namespaced as `/the-pass:run`,
`/the-pass:research`, and the other five shared skills.

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

For the published release:

```text
/plugin marketplace add mightymattys/the-pass
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
- coordinator: main Claude session routing to those three roles, with no direct file tools.

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
model. It reports the versioned model profiles but does not claim account access. `inspect`
validates limits, paths, roles, objective screening, capability routing, and sanitized argv
without execution.

## Model Routing

`AgentTask` accepts `workload_class: auto|routine|standard|complex|critical` and
`model_profile: auto|economy|balanced|deep`. Both default to `auto`; automatic workload is
conservatively `standard`. The profile is a minimum rather than an override.

| Resolved profile | Codex request | Claude request |
| --- | --- | --- |
| `economy` | `gpt-5.6-luna`, low effort | `claude-sonnet-5`, default effort |
| `balanced` | `gpt-5.6-terra`, medium effort | `claude-opus-4-8`, medium effort |
| `deep` | `gpt-5.6-sol`, high effort | `claude-fable-5`, high effort |

`critical` raises the selected deep model to its critical effort. A worktree task or native
subagent call cannot resolve below `balanced`. Role capability requirements are checked before
process creation. Claude agents inherit the broker-selected model and effort; no agent frontmatter
may override them.

The catalog lives in the packaged orchestration policy. Tasks cannot supply arbitrary model IDs.
The policy permits only two or three current models per provider and rejects any Codex catalog
below the GPT-5.6 family; there is no legacy economy fallback.
`inspect` and every `agent_run` expose the requested model, effort, resolved profile, capabilities,
rationale, and routing-policy fingerprint. The receipt describes the requested provider model;
`doctor` and offline CI do not test account entitlement or provider alias resolution.

Whole-workflow routing is stage-aware. `the-pass agents route --stage <stage>` prefers Claude for
research synthesis and adversarial/statistical review, Codex for implementation, data, simulation,
paper, and risk packaging, and a provider different from `--author-provider` for independent
review. Preflight and gate-recording stages are deterministic and request no model. The route is
policy-versioned and reports its fingerprint and rationale.

To supervise the complete queue with locally authenticated provider CLIs:

```bash
the-pass workflow execute --state <state> --author-provider codex \
  --execute --format json --driver auto
```

The auto driver gives the selected CLI workspace tools for exactly one stage, so it is distinct
from the narrower cross-provider broker below. It is explicitly enabled, may incur provider cost,
and is supervised through durable state and gate verification. The broker remains preferable for
one isolated read-only review or unapplied worktree patch.

Explicit execution:

```bash
the-pass agents dispatch path/to/agent-task.yaml \
  --output-dir reports/agents --execute --format json
```

Execution uses the user's existing Codex or Claude CLI authentication and may incur usage or API
cost. The broker never reads or records credential values and does not forward direct API-key
environment variables; use the provider CLI's local authenticated configuration. It makes one
attempt, enforces the task's timeout/output/budget bounds, and records a create-only `AgentRun`.
Only one external provider dispatch may run per local user at a time. This process lock prevents a
delegated provider from starting another broker call while its parent is active. Parallel research
or review should use the bounded native subagents inside that one provider session. On POSIX the
lock is anchored under the operating-system account home at `~/.cache/the-pass/locks`, not under an
environment-selected temporary directory, and every directory component is owner/symlink checked.

Broker-managed Codex ignores user config and execution rules, clears MCP/hook/plugin config, and
disables app, browser, computer-use, hook, plugin, image, and multi-agent features. Broker-managed
Claude loads no user/project/local settings, uses an empty strict MCP config, disables Chrome and
slash commands, and receives only the explicit The Pass plugin plus its role tool allowlist. Local
provider authentication remains available, but user connectors and unrelated provider plugins do
not enter delegated tasks.

Claude Code may return schema output in `structured_output`, as a raw result JSON string, or as one
JSON code fence inside the standard result envelope. The broker accepts exactly one `json` fence,
ignores surrounding prose as non-authoritative, and applies the same schema, task identity, path,
and evidence checks in every case.

Provider generation uses a deliberately small structured-output schema supported by both CLIs.
That schema is not evidence authority: the broker always revalidates the extracted object against
the stricter public `agent_result.schema.json` before it can complete.

## Write Isolation

`researcher` and `reviewer` tasks must use `read_only`. `implementer` tasks use
`worktree_patch` and declare narrow `allowed_write_paths`. The broker creates a unique detached
worktree from current `HEAD`, checks every changed path, emits `agent-patch-<run-id>.patch`, and
deletes the worktree. Allowed paths are checked both in the caller tree and again against committed
`HEAD` after worktree creation, closing symlink drift between dirty state and the detached tree. It
never applies, stages, commits, or pushes the patch.

Caller uncommitted changes are not included in that worktree. Apply a returned patch only after
reviewing it and running the normal repository validation matrix. `agent_run` validation reads the
current patch bytes and rejects missing, symlinked, or fingerprint-mismatched patch evidence.

## Safety and Authority

- Cross-provider depth is one; the broker rejects active nested or concurrent external dispatches
  using both runtime depth and a per-user OS lock.
- External calls are globally serialized per local user and residual provider child process groups
  are terminated before the lock is released.
- Broker-managed Claude native delegation is read-only and may invoke only the `researcher` and
  `reviewer`; the full coordinator/implementer route is available only in a user-controlled native
  main session.
- Its `acceptEdits` permission mode enables those named tools to run; the coordinator itself has no
  read, write, edit, search, or shell tool, and both permitted specialists deny writes and nesting.
- Dangerous Codex/Claude permission bypass flags are forbidden.
- Claude read-only tasks receive only read/search tools; write tasks receive edit/write tools but
  no Bash or Agent tool.
- Codex uses `read-only` or isolated `workspace-write` sandbox mode.
- Gate, ledger, policy, plugin, release, schema, security, and live-boundary paths cannot be
  changed by broker-managed patches.
- Broker receipts and patches cannot be written into a protected workspace path.
- Agent findings may inform normal review artifacts but cannot append or replace a
  `gate_decision`.
- No broker command places orders, authenticates to a venue, or unlocks `live_gate`.

Default CI uses fixture provider executables and makes no authenticated provider call. Real
cross-provider smoke tests are manual and opt-in.

# Cross-Agent Plugin and Orchestration Plan

Status: implemented and verified

Plan date: 2026-07-10

Target version: `0.9.0`

## 1. Objective

Make The Pass a validated plugin for both Codex and Claude Code while preserving one shared set
of seven domain skills. Add an optional provider-neutral broker so a Codex session can delegate a
bounded task to Claude Code and a Claude Code session can delegate a bounded task to Codex.
Support native subagents for context isolation and role separation without creating an unbounded
agent hierarchy.

This work extends the research framework. It does not add live execution, authenticated market
access, autonomous gate approval, or an always-running agent service.

## 2. Locked Decisions

1. The public skill API remains exactly `run`, `research`, `test`, `review`, `paper`, `plate`, and
   `status`.
2. `skills/<name>/SKILL.md` is the shared source for Codex and Claude Code. There are no copied
   Claude-specific skill bodies.
3. Codex keeps `.codex-plugin/plugin.json`; Claude Code gets
   `.claude-plugin/plugin.json` and a distributable marketplace catalog.
4. Native subagents are preferred for bounded exploration, implementation, and review inside the
   current runtime. Cross-provider delegation is optional and explicit.
5. The Python broker invokes only locally installed `codex` and `claude` CLIs. It contains no
   vendor API key loader, hosted agent service, or direct model API client.
6. Cross-provider delegation depth is one. A delegated Codex process cannot delegate back to
   Claude, and a delegated Claude process cannot delegate back to Codex.
7. External-agent calls are never retried automatically and always have time, output, and Claude
   spend limits.
8. Read-only tasks run against the requested repository. Write tasks run only in a detached
   temporary git worktree and return a patch artifact; the broker never applies the patch.
9. An agent review may produce findings but cannot append a gate decision or satisfy reviewer
   independence by assertion. Existing exact-package gate code remains authoritative.
10. Default CI performs no model call, authentication check, or network request. Provider process
    tests use fixture executables.
11. Neither provider is allowed to use dangerous permission bypass flags through the broker.
12. Version `0.9.0` is a minor release because the Python and plugin interfaces are additive.
13. External provider dispatch is serialized by a per-user process lock. Parallel work uses native
    subagents inside one bounded provider call; a second broker call fails closed.
14. Broker-managed providers do not load user/project MCP servers, connectors, unrelated plugins,
    hooks, rules, or provider-side multi-agent features.

## 3. Supported User Flows

### 3.1 Native orchestration

- `/the-pass:run` may use native subagents when the host exposes them.
- Research and audit subagents are read-only.
- An implementation subagent works in an isolated worktree or returns a proposed patch.
- The main agent remains responsible for validating and accepting outputs.

### 3.2 Codex delegates to Claude Code

1. Codex creates an `AgentTask` with `caller_provider: codex` and
   `target_provider: claude`.
2. `the-pass agents inspect` validates the task and prints the exact safe invocation without
   executing it.
3. `the-pass agents dispatch --execute` invokes `claude -p` with bounded tools, no session
   persistence, structured output, a budget cap, and the The Pass Claude plugin loaded.
4. The broker validates the structured result and writes an `AgentRun` receipt.
5. For write mode, only an unapplied patch and changed-path list leave the temporary worktree.

### 3.3 Claude Code delegates to Codex

The same contract applies with providers reversed. The broker invokes `codex exec` in ephemeral
mode with an explicit sandbox, structured output schema, and no approval/sandbox bypass. The
result uses the same `AgentResult` and `AgentRun` schemas.

### 3.4 Independent review

- The orchestrator may ask the other provider for a read-only adversarial review.
- The result records provider, binary version, role, task hash, result hash, and evidence paths.
- The main workflow may convert confirmed findings into normal review artifacts.
- Promotion still requires `the-pass gate evaluate` and all existing owner/reviewer checks.

## 4. Plugin Packaging

### 4.1 Codex

Keep `.codex-plugin/plugin.json` as the Codex authority. Update its version and description to
mention optional bounded cross-runtime delegation. The official Codex plugin validator must pass.

### 4.2 Claude Code

Add `.claude-plugin/plugin.json` with:

- `name: the-pass`;
- version, description, author, homepage, repository, license, and keywords;
- default `skills/` and `agents/` discovery from the plugin root.

Add `.claude-plugin/marketplace.json` so users can add `mightymattys/the-pass` as a marketplace and
install `the-pass@the-pass-tools`. The plugin entry itself uses the GitHub repository
with `ref: v0.9.0`; mutable branch installation is development-only. Claude's marketplace schema
has no archive-digest field, so release integrity is additionally checked by the existing
annotated-tag release workflow and published SHA-256 asset list.

Required validation:

```bash
claude plugin validate . --strict
claude --plugin-dir .
```

The interactive smoke confirms `/the-pass:run` and the four namespaced agents are discoverable.
Automated CI validates structure but does not start an authenticated Claude session.

### 4.3 Shared skills

The seven skills gain a concise `Agent Delegation` section. It defines when to use native
subagents, when cross-provider review is useful, and when delegation must be blocked. Provider
details live in one cross-runtime document to avoid inflating every skill.

## 5. Native Subagents

Claude plugin agents:

| Agent | Purpose | Tools | Writes |
| --- | --- | --- | --- |
| `researcher` | source and repository evidence collection | read/search/web tools | none |
| `implementer` | scoped code or artifact proposal | read/search/edit/write | isolated worktree only |
| `reviewer` | adversarial evidence and code review | read/search | none |
| `coordinator` | bounded routing when used as the session's main agent | scoped named Agent tools only | none directly |

All definitions set a finite `maxTurns`. Reviewer and researcher deny write tools. The coordinator
may spawn only the three named plugin agents when selected as the main session agent with
`claude --agent`; it has no direct read/write/search tools and must not itself be spawned as a
subagent. Specialists receive no `Agent`
tool, so they form one native delegation level and cannot recursively spawn another subagent.

Codex does not receive a second, incompatible agent-definition format. The shared skills tell
Codex to use available native subagent tooling for the same roles and to preserve the same
read/write boundaries. The deterministic broker covers cross-provider invocation.

## 6. Agent Artifacts

### 6.1 `AgentTask` v1

Required fields:

- `schema_version`, `task_id`, `created_at`;
- `caller_provider`, `target_provider`;
- `role`: `researcher|implementer|reviewer`;
- `objective` and optional `acceptance_criteria`;
- `workspace_root` and `input_paths`;
- `mode`: `read_only|worktree_patch`;
- `allowed_write_paths` for `worktree_patch`;
- `timeout_seconds`, `max_output_bytes`, and optional `max_budget_usd`;
- optional `model_profile: auto|economy|balanced|deep` and
  `workload_class: auto|routine|standard|complex|critical`, both defaulting to `auto`;
- `allow_native_subagents`;
- `forbidden_actions` including gate mutation, credential access, live code, and recursive
  cross-provider calls.

Validation rules:

- caller and target must differ;
- runtime depth is derived only from the broker-controlled `THE_PASS_AGENT_DEPTH` environment
  value; no caller-supplied task field participates in enforcement;
- review and research roles are always read-only;
- write paths must be relative, normalized, non-empty, and inside the repository;
- input paths must exist and resolve inside the repository;
- timeout/output/budget values must remain within policy maxima;
- model routing uses only the structured task fields and versioned capability catalog; arbitrary
  model IDs and free-text complexity classification are forbidden;
- a normalized semantic scanner rejects obvious requests for real orders, credentials, gate
  approval, permission bypass, or recursive delegation. This scanner is defense-in-depth, not the
  security boundary: sandbox/tool restrictions, worktree isolation, protected paths, result
  validation, and gate code remain authoritative even when text evades classification.

### 6.2 `AgentResult` v1

Provider-neutral structured response:

- `task_id`, `status: complete|blocked|failed`;
- concise `summary`;
- `findings` with severity, title, evidence paths, and recommendation;
- `changed_paths`;
- `next_actions`;
- `assumptions` and `issues`.

Read-only results must have no changed paths. A result cannot claim gate passage or human
approval.

### 6.3 `AgentRun` v1

Create-only receipt written by the broker:

- run/task IDs and task fingerprint;
- caller and target providers;
- provider binary path and version;
- requested/resolved model profile, workload class, requested model, reasoning effort,
  capabilities, rationale, and routing-policy fingerprint;
- exact orchestration policy schema/interface version and fingerprint;
- role, mode, working-directory strategy, and effective limits;
- sanitized argv, start/end timestamps, duration, and exit code;
- stdout/stderr SHA-256 and truncation flags;
- result fingerprint and validated result;
- patch path/fingerprint when applicable;
- cost and session metadata when the provider reports them;
- status and exact blocker/error.

The receipt stores no environment values, tokens, raw credentials, or unbounded provider logs.
The broker refuses to overwrite an existing receipt. V1 receipts are fingerprinted but not signed
or hash-chained; cryptographic multi-run ledgering is outside this additive release.

## 7. Broker CLI

New scheduler-neutral group:

```text
the-pass agents doctor [--provider codex|claude|all]
the-pass agents inspect <task>
the-pass agents dispatch <task> --output-dir <dir> --execute
```

All commands support `--format text|json` and the standard JSON envelope.

### 7.1 `doctor`

- Locate the selected binaries and run only `--version`.
- Report availability and supported capability assumptions.
- Do not test authentication or contact a model endpoint.

### 7.2 `inspect`

- Validate `AgentTask` and orchestration policy.
- Resolve paths and produce a sanitized invocation preview.
- Never execute a provider.

### 7.3 `dispatch`

- Require `--execute` to make external cost and tool use explicit.
- Reject execution when already inside a delegated process at the policy depth limit.
- Use `subprocess` argv arrays with `shell=False`.
- Pass the prompt through stdin, not a shell command line.
- Set a minimal child environment plus recursion metadata.
- Hold the exclusive external-dispatch lock until provider descendants are terminated and the
  receipt is finalized.
- Enforce timeout, output cap, and one attempt.
- Validate structured output before writing a successful receipt.
- Return exit `0` for a complete validated result, `2` for a valid blocked result, `1` for invalid
  input/provider failure, and `3` for a forbidden safety request.

## 8. Provider Adapters

### 8.1 Codex adapter

Allowed invocation characteristics:

- `codex exec`;
- `--ephemeral`, `--json`, `--color never`;
- `--sandbox read-only` or `workspace-write` only inside the temporary worktree;
- `--cd` set to the resolved execution root;
- packaged `AgentResult` output schema;
- a Codex/Claude-compatible generation subset is supplied to the provider, then every returned
  object is revalidated against the stricter public `AgentResult` schema and semantic checks;
- no `--dangerously-bypass-approvals-and-sandbox`;
- no extra writable directories;
- no session resume.
- ignore user config and execution rules; clear MCP, hook, and plugin configuration;
- disable provider apps, browser/computer use, hooks, unrelated plugins, image generation, and
  provider-native multi-agent features.

### 8.2 Claude adapter

Allowed invocation characteristics:

- `claude -p` with `--output-format json`;
- `--no-session-persistence`;
- packaged JSON output schema;
- `--plugin-dir` pointing to The Pass plugin;
- read-only roles use `--permission-mode plan --tools Read,Glob,Grep` plus
  `--disallowedTools Write,Edit,Bash,Agent`;
- broker-managed native delegation uses `acceptEdits` only to permit tool execution, while its
  tool allowlist contains only scoped `researcher|reviewer` agents and explicitly denies direct
  file/shell tools plus `implementer|coordinator`;
- worktree implementation uses edit/write tools without unrestricted Bash;
- `--max-budget-usd` always set from the bounded task/policy;
- no `--dangerously-skip-permissions`;
- no session resume or remote control.
- load no user/project/local setting sources, use an empty strict MCP configuration, disable Chrome
  and slash commands, and load only the explicit The Pass plugin.

Provider stdout parsers accept only documented final-result envelopes and fail closed on malformed
or ambiguous output. Claude's documented `result` string fallback may contain either the raw JSON
object or exactly one explicitly labelled `json` code fence; surrounding prose is non-authoritative
and ignored when no second fence exists. Unknown event fields are ignored, but required result
fields are never inferred and the extracted object still receives full schema and semantic
validation.

## 9. Worktree Patch Isolation

For `worktree_patch`:

1. Require a git repository and resolve its root.
2. Create a uniquely named temporary detached worktree from current `HEAD` using the task and run
   IDs plus an OS-generated random suffix.
3. Recheck every allowed write path against the detached `HEAD` for symlink traversal, then run the
   target agent only inside that worktree.
4. Collect tracked and untracked changed paths.
5. Reject forbidden or out-of-scope paths.
6. Build a binary-safe patch artifact and fingerprint it.
7. Remove the temporary worktree in a `finally` block.
8. Never apply, stage, commit, or push the patch.

The initiating agent or human reviews and applies the patch through the normal repository
workflow. Existing uncommitted caller changes are never overwritten or silently included.

## 10. Security and Failure Model

Threats and controls:

| Threat | Control |
| --- | --- |
| Codex/Claude recursion loop | non-lowerable environment depth, exclusive dispatch lock, child process-group cleanup |
| cost runaway | timeout, Claude USD cap, one attempt, finite agent turns |
| prompt injection from repository/source | role prompt, tool restrictions, no credential access |
| unreviewed writes | detached worktree and unapplied patch |
| shell injection | argv arrays and stdin prompt, never `shell=True` |
| secret leakage | environment allowlist, output caps, hashes instead of raw logs |
| fake independent approval | agent results cannot write or append gate decisions |
| live trading expansion | forbidden task semantics and existing public live-path scanner |
| provider CLI drift | versioned policy, doctor output, fixture contract tests, opt-in live smoke |
| user worktree damage | no writes outside broker-created worktree |

Hard failures include missing binary, invalid task, authentication/provider error, timeout,
malformed output, changed path outside scope, non-empty read-only change set, and recursion depth.
Every failure returns a structured issue and, after execution starts, an `AgentRun` receipt.

## 11. Policy

Add `config/agent-orchestration.v1.yaml` and an identical packaged copy. It defines:

- providers and binary names;
- role/mode matrix;
- maximum timeout, output bytes, Claude budget, and cross-provider depth;
- one active external provider call per local user;
- allowed and forbidden CLI flags;
- protected repository paths;
- role prompts and output schema version;
- no-retry and no-auto-apply rules.

The packaged policy is the runtime authority. Repository and wheel validation compare the source
and packaged copies byte-for-byte; source-checkout commands also fail if both copies exist and
differ.

Protected paths include every existing gate and live-boundary authority: gate, ledger, validator,
workflow, agent-broker, and live-boundary modules; packaged and source policy directories;
gate/risk/skill/agent policy files; gate-decision, human-decision, approval, audit, receipt, and
live-risk schemas; plugin manifests; release workflow; and security documentation. A coverage test
asserts that the explicit critical-path inventory remains a subset of policy-protected paths.

## 12. Documentation and ADR

Deliver:

- this plan;
- `ADR-0010-portable-agent-orchestration.md`;
- `docs/plugin/CROSS_RUNTIME.md` with installation and usage;
- README and installation updates for Codex and Claude Code;
- shared skill and agent instructions for Claude; a plugin-root `CLAUDE.md` is deliberately not
  shipped because Claude Code ignores it as plugin context and strict validation warns about it;
- changelog entry and version alignment.

Documentation must distinguish:

- plugin installation from cross-provider execution;
- native subagents from external CLI delegation;
- agent findings from authoritative gate decisions;
- framework capability from candidate promotion;
- offline validation from opt-in authenticated smoke tests.

## 13. Test Matrix

### Unit

- task/result/run schema validation;
- path normalization and traversal rejection;
- role/mode rules;
- recursion and budget boundaries;
- a forged initial-depth claim submitted while `THE_PASS_AGENT_DEPTH=1` is rejected;
- obvious forbidden objectives are rejected while tests document that text classification is
  defense-in-depth only;
- command construction for both providers;
- dangerous flag absence;
- output parsing and truncation;
- timeout and non-zero provider exits.

### Fixture provider contracts

- fake Codex and Claude executables return valid structured results;
- malformed JSON, missing result, conflicting results, and excessive output fail closed;
- provider stderr is hashed and bounded;
- no automatic retry occurs.

### Worktree isolation

- allowed change produces a patch and leaves caller tree unchanged;
- out-of-scope and protected-path changes are blocked;
- read-only task producing a write is blocked;
- temporary worktree is removed after success, failure, and timeout;
- untracked files appear in the patch artifact.
- a concurrent or nested external dispatch fails before provider execution;
- native subagents remain available for bounded parallel read-only work.

### Plugin

- official Codex plugin validator passes;
- `claude plugin validate . --strict` passes;
- exactly seven skills are exposed;
- four Claude agents validate with finite turns and restricted tools;
- marketplace manifest validates and points to the public repository.

### Integration

- `agents doctor` is offline and deterministic apart from installed versions;
- `agents inspect` never executes a provider;
- fixture Codex-to-Claude and Claude-to-Codex dispatches create valid receipts;
- the broker rejects nested or concurrent external dispatch while another dispatch is active;
- agent result cannot mutate a gate or live boundary.

### Existing matrix

All existing 143 tests, Python 3.9/3.12 CI, Ruff, public validator, skill validators, wheel
validation, secret scan, and live-order scan must continue to pass. Default CI remains offline.

## 14. Rollout

1. Add schemas, policy, and pure command builders.
2. Add fixture-backed broker execution and worktree isolation.
3. Add Claude plugin manifest, marketplace, and agents.
4. Update shared skills and documentation.
5. Run strict plugin validators and the full offline matrix.
6. Add an optional manual smoke command for authenticated local testing; never add it to default
   CI.
7. Release as `0.9.0` only after protected review and release audit.

## 15. Acceptance Gates

Implementation is complete only when:

- both plugin validators pass;
- Codex and Claude discover the same seven skills under `/the-pass:*`;
- all four Claude agents validate;
- fixture dispatch works in both directions;
- writes never touch the caller workspace and produce only an unapplied patch;
- recursion, timeout, output, budget, role, and path tests pass;
- external agents cannot append gate decisions or cross the live boundary;
- the packaged wheel contains schemas and policy;
- all existing and new tests pass on Python 3.9 and 3.12;
- no P0/P1 audit finding remains.

## 16. Plan Audit

The plan was checked against the installed `codex-cli 0.144.0-alpha.4`, Claude Code `2.1.153`,
the accepted seven-skill workflow, exact-package gate semantics, package distribution rules, and
the public live lock.

Resolved design risks:

- Shared skills avoid Codex/Claude behavior drift.
- Explicit provider adapters avoid model-specific logic in domain skills.
- Worktree patches avoid trusting a foreign agent with the caller workspace.
- Depth one avoids Codex/Claude ping-pong and makes cost bounds comprehensible.
- Structured results and receipts make provider output auditable.
- Gate decisions remain outside the broker, preserving independent promotion semantics.
- Fixture CLIs make default CI deterministic and offline.
- A marketplace manifest makes Claude installation reproducible instead of relying on directory
  auto-discovery.

Independent Claude plan audit found no P0 and six P1 design issues. All were resolved before
implementation:

- Coordinator topology now distinguishes a main-session coordinator from non-recursive
  specialists.
- Runtime depth is broker-derived and cannot be reset by task metadata.
- Free-text screening is explicitly defense-in-depth; mechanical controls remain authoritative.
- Claude marketplace installation is pinned to `v0.9.0` and release checksums cover artifacts.
- Critical gate/live authorities have an explicit protected-path coverage test.
- Claude read-only enforcement names exact permission and tool flags.

P2 resolutions: stable exit `2` is retained because it is already The Pass's documented semantic
non-promotion code; worktree names are unique; packaged policy is runtime-authoritative; receipts
are create-only but not claimed to be cryptographically immutable; and `mightymattys/the-pass` was
confirmed from the configured git remote.

No implementation decision is left as `TBD`. Provider choice is policy-driven through versioned
`economy`, `balanced`, and `deep` profiles. Claude rolling aliases and provider account access are
explicit runtime boundaries; the requested model and routing hash remain auditable.

## 17. Implementation Evidence

The implementation completed on 2026-07-10 with:

- 172 repository tests passing in the final complete matrix recorded in
  `reports/CROSS_AGENT_ORCHESTRATION_AUDIT_0.9.0.md`;
- all seven Codex skill validators, the Codex plugin validator, and both strict Claude plugin
  validators passing;
- clean wheel installation validating the packaged policy, both result schemas, and
  `the-pass agents inspect` without a source checkout;
- fixture Codex-to-Claude and Claude-to-Codex dispatches, serialization, malformed output, timeout,
  output/patch caps, policy hash, protected output, patch tampering, path traversal, symlink drift,
  provider-config isolation, child cleanup, and worktree cleanup coverage;
- authenticated read-only smoke dispatches completing in both real provider directions with
  create-only receipts and no workspace writes;
- an authenticated broker-managed Claude coordinator smoke completing through its scoped reviewer
  subagent while the coordinator had no direct file or shell tools;
- authenticated `sonnet/medium` and `gpt-5.6-luna/low` routing smokes completing with the requested
  model and effort recorded in valid receipts.

The authenticated smoke exposed provider-specific output differences that fixture-only testing
could not reveal. Those findings were fixed before completion: Claude may return one fenced JSON
document in its result envelope, Claude requires a stronger exact-key prompt, and Codex accepts a
smaller structured-output schema subset. Every provider object is still validated afterward by the
strict public `AgentResult` schema and semantic checks.

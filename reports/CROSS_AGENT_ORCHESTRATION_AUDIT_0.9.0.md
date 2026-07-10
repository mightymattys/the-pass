# Cross-Agent Orchestration Audit 0.9.0

Audit date: 2026-07-10

Branch: `codex/cross-agent-orchestration`

Verdict: pass, pending normal protected-branch review and release process

## Scope

This audit covers the shared Codex/Claude Code plugin surface, native Claude subagents, the
provider-neutral `the-pass agents` broker, artifact schemas, worktree isolation, safety policy,
documentation, package distribution, and real read-only interoperability. It does not authorize a
trading gate, live execution, venue credentials, or automated patch acceptance.

## Delivered

- One shared set of seven skills for Codex and Claude Code.
- Claude plugin and pinned-release marketplace manifests.
- Four finite Claude agents: coordinator, researcher, implementer, and reviewer.
- `agent_task`, strict `agent_result`, provider-generation result, and `agent_run` schemas.
- `agents doctor`, `agents inspect`, and explicit `agents dispatch --execute` CLI commands.
- Depth-one recursion control, one attempt, timeout/output/budget bounds, minimal environment,
  create-only receipts, exact policy fingerprint, protected paths, and no automatic patch apply.
- Read-only review/research and detached-worktree implementation with binary patch output.

## Findings Resolved

| Severity | Finding | Resolution |
| --- | --- | --- |
| P1 | Broker-managed Claude coordinator could expose the implementer during a read-only delegated task. | Broker CLI now permits only researcher/reviewer and explicitly denies implementer/coordinator. |
| P1 | Codex structured result file and generated patch could exceed the process stream cap. | Both are checked against `max_output_bytes` before parsing or persistence. |
| P1 | Allowed write scope could traverse an existing symlink. | Any symlink component in an allowed write path fails before worktree creation. |
| P1 | Claude CLI may return valid schema data inside one JSON fence rather than `structured_output`. | One unambiguous fenced object is accepted, then strictly revalidated; competing objects fail. |
| P1 | Claude could invent additional result metadata despite `--json-schema`. | Prompt now enumerates the exact result keys; strict post-validation remains authoritative. |
| P1 | Full JSON Schema keywords are not accepted by Codex response format. | A minimal provider-generation schema is used; the full public schema and semantic validator run afterward. |
| P2 | Non-zero provider exits lost safe structured diagnostic metadata. | Receipts retain bounded event/subtype, session, and cost metadata without raw logs. |
| P2 | Direct API-key environment variables were forwarded to provider processes. | They were removed from the child environment allowlist; local CLI authentication remains external. |

No open P0 or P1 finding remains.

## Second-Pass Adversarial Audit

A second full diff and runtime audit was performed after the initial green PR. It reviewed provider
configuration loading, recursion resistance, process descendants, dirty-tree versus committed-tree
path resolution, broker output placement, receipt semantics, patch bytes, and native-agent name
resolution. The following additional findings were confirmed and fixed:

| Severity | Finding | Resolution |
| --- | --- | --- |
| P1 | Codex and Claude inherited user/project MCP, connector, plugin, hook, and rule configuration. | Codex now ignores user config/rules, clears MCP/hooks/plugins, and disables unrelated capabilities; Claude loads no setting sources and uses an empty strict MCP config. |
| P1 | Environment depth could be unset by a delegated shell before starting another broker process. | External dispatch is serialized with a per-user OS lock, supplied depth cannot lower inherited depth, and residual POSIX process groups are terminated before unlock. |
| P1 | `--output-dir` could place broker artifacts under protected governance paths. | Output paths are resolved and rejected before execution when they are inside a protected workspace path. |
| P1 | Allowed paths were checked in the dirty caller tree but not against detached `HEAD`. | Every allowed path is rechecked for symlink traversal after worktree creation. |
| P1 | `agent_run` validated the recorded patch hash format but not the current patch bytes. | Semantic validation now requires an existing regular patch file and verifies its SHA-256. |
| P1 | The protected-path inventory omitted CI, CLI, validators, agent definitions, packaged agent schemas, and build metadata. | Policy coverage now includes all of those authorities and remains source/package identical. |
| P2 | Bare agent names could resolve ambiguously when another Claude plugin defines the same roles. | Coordinator and broker allowlists now use scoped `the-pass:*` agent names. |
| P2 | Claude fenced JSON could be rejected when harmless prose outside the sole JSON fence contained braces. | The parser requires exactly one labelled `json` fence and ignores all surrounding prose as non-authoritative before strict validation. |

No second-pass P0 finding was found. All second-pass P1 findings are closed by code and regression
tests before the final verdict.

## Capability-Routing Audit

A third pass reviewed model capability, cost, latency, effort, provider drift, task-controlled
overrides, native-agent inheritance, and receipt traceability. It produced these resolved findings:

| Severity | Finding | Resolution |
| --- | --- | --- |
| P1 | Provider defaults made model capability and cost dependent on untracked local/account settings. | A versioned policy now resolves structured workloads to explicit `economy`, `balanced`, or `deep` provider profiles. |
| P1 | Claude agent frontmatter could override a broker-selected reasoning effort. | All four agents now inherit model and effort; public validation rejects local agent overrides. |
| P1 | A receipt could state a model different from provider argv or the recorded policy profile. | Semantic validation checks model, effort, capabilities, routing hash, and sanitized argv against the current recorded policy. |
| P2 | Nested `findings` shape was not explicit enough for an older Claude CLI despite JSON Schema. | The exact four-key finding object is included in the prompt; strict post-validation remains authoritative. |

The catalog was checked against official Codex and Claude Code model/configuration documentation
on 2026-07-10. Tasks cannot supply arbitrary model IDs, and the broker does not silently retry or
fall back to another profile.

## Verification

The final audit matrix requires all of the following to pass:

```bash
uv lock --check
uv run ruff check .
uv run python scripts/validate_public_repo.py
uv run python -m unittest discover -s tests -v
claude plugin validate .claude-plugin/plugin.json --strict
claude plugin validate . --strict
uv build --out-dir <temporary-directory>
uv run python scripts/validate_distribution.py <wheel>
```

All seven `skills/*/SKILL.md` files also pass the official Codex skill validator, and the repository
passes the official Codex plugin validator. The final offline suite contains 172 passing tests.

Authenticated read-only smoke results:

| Direction | Result | Workspace writes | Notes |
| --- | --- | --- | --- |
| Codex caller to Claude target | complete | none | Valid strict result; reported Claude cost was USD 0.1181065. |
| Claude caller to Codex target | complete | none | Valid strict result; Codex CLI does not report a cost field. |
| Codex caller to Claude reviewer subagent | complete | none | Scoped coordinator had no direct file/shell tools; reviewer returned `# The Pass`; reported Claude cost was USD 0.009881. |
| Codex caller to Claude balanced profile | complete | none | Requested `sonnet` with medium effort; strict result passed; reported Claude cost was USD 0.03095135. |
| Claude caller to Codex economy profile | complete | none | Requested `gpt-5.6-luna` with low effort; strict result passed. |

Smoke receipts were intentionally written under a temporary directory and are not committed as
portable project evidence. The stable evidence is the fixture-backed regression suite and this
sanitized audit record.

## Code Evidence

| Control | Evidence |
| --- | --- |
| Policy, catalog, and capability-aware selection | `src/the_pass/agent_orchestration.py:125`, `src/the_pass/agent_orchestration.py:165`, `src/the_pass/agent_orchestration.py:237` |
| Provider config isolation, explicit model/effort, and scoped native-agent allowlist | `src/the_pass/agent_orchestration.py:564` |
| Bounded process groups and strict provider-result parsing | `src/the_pass/agent_orchestration.py:776`, `src/the_pass/agent_orchestration.py:790`, `src/the_pass/agent_orchestration.py:955` |
| Protected output path and serialized dispatch | `src/the_pass/agent_orchestration.py:1331` |
| Receipt chronology, model-policy consistency, and current patch-byte verification | `src/the_pass/validator.py:664` |
| Plugin topology, model inheritance, and policy-copy checks | `scripts/validate_public_repo.py:207`, `scripts/validate_public_repo.py:428` |
| Agent-only coordinator contract | `agents/coordinator.md:1` |

## Residual Boundaries

- Cross-provider execution depends on locally installed and authenticated CLIs and may incur cost.
- Provider versions can drift; `agents doctor` reports versions but does not contact a model.
- Claude aliases are rolling provider aliases, and account-level model entitlement is not verified
  offline. Receipts record the requested model, not an unverifiable claim about alias resolution.
- Read-only isolation relies on Codex sandbox enforcement or Claude tool denial; no credentials are
  loaded by The Pass, but users remain responsible for provider CLI configuration.
- Agent output is an evidence input only. It cannot append a gate decision, satisfy human approval,
  place an order, apply a patch, commit, or push.
- Default CI remains fully offline. Authenticated smoke is manual and opt-in.

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
passes the official Codex plugin validator. The final offline suite contains 164 passing tests.

Authenticated read-only smoke results:

| Direction | Result | Workspace writes | Notes |
| --- | --- | --- | --- |
| Codex caller to Claude target | complete | none | Valid strict result; reported Claude cost was USD 0.1181065. |
| Claude caller to Codex target | complete | none | Valid strict result; Codex CLI does not report a cost field. |

Smoke receipts were intentionally written under a temporary directory and are not committed as
portable project evidence. The stable evidence is the fixture-backed regression suite and this
sanitized audit record.

## Residual Boundaries

- Cross-provider execution depends on locally installed and authenticated CLIs and may incur cost.
- Provider versions can drift; `agents doctor` reports versions but does not contact a model.
- Read-only isolation relies on Codex sandbox enforcement or Claude tool denial; no credentials are
  loaded by The Pass, but users remain responsible for provider CLI configuration.
- Agent output is an evidence input only. It cannot append a gate decision, satisfy human approval,
  place an order, apply a patch, commit, or push.
- Default CI remains fully offline. Authenticated smoke is manual and opt-in.

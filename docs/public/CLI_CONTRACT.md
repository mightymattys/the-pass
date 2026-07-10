# CLI Contract

The CLI is the scheduler-neutral and engine-neutral interface for validating evidence and
running reference workflows.

## Output Formats

Every command supports `--format text|json`. JSON output always contains:

```json
{
  "ok": true,
  "status": "complete",
  "artifact_paths": [],
  "issues": [],
  "receipt_id": null
}
```

Commands may add fields, but they may not remove or change the meaning of these five keys in a
compatible release. `issues` rows contain at least `path` and `message`. Artifact paths are
absolute for newly written local artifacts unless a documented receipt uses workspace-relative
paths.

## Exit Codes

| Code | Meaning |
| --- | --- |
| `0` | operation succeeded or evaluated gate passed |
| `1` | invalid input, schema failure, missing evidence, or technical failure |
| `2` | valid research result is `blocked`, `revise`, `kill`, `frozen`, or otherwise not promoted |
| `3` | operation is forbidden by the public safety boundary |

Exit code `2` is not a software failure. It means the tool successfully evaluated evidence and
declined promotion.

## Command Groups

- `validate`, `validate-package`: artifact and package validation.
- `data`, `features`: canonical quality and deterministic feature evidence.
- `screen`, `backtest`: preregistered diagnostics and deterministic reference simulation.
- `robustness`, `risk`: statistical and policy-independent risk evidence.
- `gate`: artifact-backed candidate gate evaluation.
- `paper`: isolated virtual paper execution.
- `automation`, `incident`: scheduler-neutral jobs and fail-closed incidents.
- `report`, `dashboard`: static read-only evidence bundles.
- `receipts`: append-only run and gate-decision ledger operations.
- `workflow`: validated local run state, evidence resume checks, package fingerprinting, and
  immutable successor creation.
- `agents`: provider discovery, non-executing task inspection, and explicit bounded delegation to
  Codex or Claude Code.

## Compatibility

- Existing required JSON keys and exit-code meanings are stable within a major version.
- New optional fields and new commands are additive minor-version changes.
- A breaking field or semantic change requires a new major version and migration note.
- Text output is for humans and is not a stable parsing interface.
- Candidate gate IDs remain `research_gate`, `paper_gate`, `risk_review`, and `live_gate`.
- Framework milestone passes never imply that a candidate gate passed.

## Workflow Authority

The additive workflow commands are:

```text
the-pass workflow start
the-pass workflow advance
the-pass workflow status
the-pass workflow fingerprint
the-pass workflow supersede
```

`start`, `advance`, and `status` manage validated local state. `fingerprint` computes package
identity without recording it. `supersede` requires `--ledger`, `--run-id`, and `--created-at`;
it proves that the exact source path is a valid recorded v2 run before creating a mutable
successor.

Workflow state is not promotion authority. Promotion and remediation use semantically replayed
v2 ledger evidence bound to the exact package ID and resolved path. A v1 row, prose label,
verdict string, copied directory, out-of-order gate row, or duplicate package ID cannot replace a
valid gate decision. Exhausted transition/remediation/no-progress budgets are terminal for that
workflow ID.

## Agent Delegation Authority

The additive agent commands are:

```text
the-pass agents doctor
the-pass agents inspect <agent-task>
the-pass agents dispatch <agent-task> --output-dir <dir> --execute
```

`doctor` checks local executable/version availability and lists policy model profiles without
testing authentication, account entitlement, or making a model call. `inspect` validates the task,
resolves its capability-aware model/effort profile, and prints a secret-free execution preview.
`dispatch` requires the explicit `--execute` flag and writes a create-only `agent_run` receipt.

Delegation is depth one. A delegated task cannot dispatch another agent, retry itself, approve a
gate, alter governance or live-safety files, or apply its own patch. Read-only tasks return
structured findings; implementation tasks run in a disposable worktree and return an unapplied
patch. External provider calls are serialized per local user, while bounded native subagents may
parallelize work inside one call. Provider user settings, MCP servers, connectors, unrelated
plugins, and hooks are excluded. The caller remains responsible for reviewing, applying, testing,
and recording any change.

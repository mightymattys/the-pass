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
- `data`, `features`: immutable adapter ingest, resumable dataset plans/builds, canonical quality,
  and deterministic features.
- `screen`, `backtest`: preregistered diagnostics and double-run strategy simulation.
- `robustness`, `risk`: strategy-driven matrices, statistics, and independent risk evidence.
- `audit`: clean custom-package reproduction through a fixed internal runner.
- `gate`: signed reviewer provenance and artifact-backed candidate gate evaluation.
- `paper`: compatibility replay and resumable custom-strategy observation.
- `automation`, `incident`: evidence-reading scheduler-neutral jobs and incidents.
- `report`, `dashboard`: static read-only evidence bundles.
- `receipts`: append-only run and gate-decision ledger operations.
- `workflow`: validated local run state, evidence resume checks, package fingerprinting,
  immutable successor creation, and explicitly enabled liveness supervision.
- `research`: conservative source-evidence scope reporting.
- `agents`: catalog freshness, provider discovery, stage-aware routing, task inspection, and explicit
  bounded delegation to Codex or Claude Code.

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
the-pass workflow execute --state <state> [--execute] --driver auto|<trusted argv>
the-pass workflow fingerprint
the-pass workflow supersede
```

`start`, `advance`, and `status` manage validated local state. `fingerprint` computes package
identity without recording it. `supersede` requires `--ledger`, `--run-id`, and `--created-at`;
it proves that the exact source path is a valid recorded v2 run before creating a mutable
successor. If the ledger already contains passed decisions, `--trusted-reviewers` or
`THE_PASS_TRUSTED_REVIEWER_REGISTRY` is also required for semantic replay.

`execute` is inspect-only unless `--execute` is present. It invokes at most one stage per cycle,
validates each resulting checkpoint, and cannot return exit `0` before the exact target gate has a
recorded pass. `--driver auto` uses authenticated local Codex/Claude CLIs and can incur provider
cost; a custom driver is treated as a trusted local executable and is launched without a shell.

Workflow state is not promotion authority. Promotion and remediation use semantically replayed
v2 ledger evidence bound to the exact package ID and resolved path. A v1 row, prose label,
verdict string, copied directory, out-of-order gate row, or duplicate package ID cannot replace a
valid gate decision. Exhausted transition/remediation/no-progress budgets are terminal for that
workflow ID.

## Strategy Runtime Authority

The additive execution commands are:

```text
the-pass data ingest --provider futures|binance|polymarket
the-pass data plan --provider futures|binance|polymarket ...
the-pass data build --plan <dataset-plan> --output <dataset>
the-pass backtest run --descriptor <json> --strategy-spec <artifact> ... \
  [--runtime-mode trusted_local|hardened] [--sandbox-launcher <executable>] \
  [--sandbox-policy <json>]
the-pass audit reproduce <package> --output <report> \
  [--sandbox-launcher <executable>] [--sandbox-policy <json>]
the-pass robustness sweep --source-package <package> --descriptor <json> \
  --variants <json> --train-size <rows> --test-size <rows> --purge <rows> \
  --embargo <rows> --null-variant-index <index> --stress-results <json> ...
the-pass candidate assemble <source-package> <candidate-package> \
  --ledger <ledger> --run-id <id> --created-at <RFC3339> \
  --robustness-report <json> --findings <artifact> \
  [--trusted-reviewers <registry>]
the-pass paper observe --descriptor <json> --batch-id <id> ...
```

`data ingest` publishes only through an atomic `COMMITTED` bundle and refuses existing output.
Public network providers require `--network`; futures requires a local archive. `backtest run`
cross-validates the StrategySpec, manifest, quality report, canonical event fingerprint, descriptor,
and execution config. The quality report must bind the exact event fingerprint and row count. It
executes two fresh credential-free workers and packages only identical
results. Exit `0` means the diagnostic operation completed, not that its blocked verdict passed a
gate.

`trusted_local` is the portable default. It reports process separation, credential stripping, and
import filtering, while explicitly reporting no OS network/filesystem enforcement and no runtime
promotion eligibility. `hardened` requires an executable launcher and a trust policy that
allowlists its exact SHA-256 and enforcement contract. Before each strategy run, The Pass executes
an active probe through the launcher for forbidden filesystem access, loopback network access, and
OS CPU/file-size limits. The launcher, policy, probe, and attestations are fingerprinted; any
missing or mismatched evidence fails closed.

`data plan` freezes a contiguous, non-overlapping chunk set. `data build` serializes builders for
one output, resumes only valid committed chunks, rejects conflicting duplicate events, and fully
revalidates an existing committed aggregate before returning it. `audit reproduce` accepts only a
validated `reproduction_spec`, a fixed runner ID, declared fingerprinted workspace files, and safe
relative paths. It executes without a shell and returns `2` when rebuilt evidence differs.

## Gate Attestation Authority

New `research_gate`, `paper_gate`, and `risk_review` passes require
`reviewer_attestation.<gate>.json`. `the-pass gate attest` signs the exact package, gate, reviewer,
provider/model/run provenance, author/reviewer separation, and review evidence hashes using
Ed25519. `the-pass gate keygen` writes a create-only mode-`0600` private key and a public
`reviewer_key_registry`. Signing reads the base64 raw private key from
`THE_PASS_REVIEW_SIGNING_KEY`; signature verification uses the package-local public registry
snapshot. Authorization additionally requires an operator-controlled matching registry outside the
package through `--trusted-reviewers` or `THE_PASS_TRUSTED_REVIEWER_REGISTRY`. A self-issued
registry therefore proves key ownership but cannot authorize a pass. Missing, mismatched, expired,
revoked, or unverifiable trust evidence produces a valid blocked result. Legacy HMAC attestations
remain readable but can never authorize a new pass; `live_gate` remains forbidden.

`robustness sweep` create-only writes `<output-stem>.registration.json` before its first worker
call. Promotion-capable v2 reports require purged walk-forward folds, a preregistered null variant,
all mandatory stress scenarios, neighboring-parameter stability, and promotion-eligible hardened
runtime cells. Artifact validation recomputes all statistics from the stored matrix.
`candidate assemble` is the only supported automatic conversion from a recorded diagnostic run to
a research candidate: it creates a ledger-linked successor, copies exact robustness/findings
evidence, derives summary fields, and validates the final package before returning it.
`receipts add`, `workflow supersede`, and `candidate assemble` all accept
`--trusted-reviewers` so a ledger containing passed decisions can be replayed under the same trust
anchor before another append or successor operation.
`paper observe` stores immutable batches, verifies cumulative replay prefixes and configuration
continuity, and returns exit `2` on a sticky freeze. A worker failure after batch commit freezes and
tracks that batch instead of leaving orphan evidence. Neither command may write a gate decision.

## Agent Delegation Authority

The additive agent commands are:

```text
the-pass agents doctor
the-pass agents catalog-check
the-pass agents route --stage <stage> [--author-provider codex|claude]
the-pass agents inspect <agent-task>
the-pass agents dispatch <agent-task> --output-dir <dir> --execute
```

`doctor` checks local executable/version availability and lists policy model profiles without
testing authentication, account entitlement, or making a model call. `inspect` validates the task,
resolves its capability-aware model/effort profile, and prints a secret-free execution preview.
`dispatch` requires the explicit `--execute` flag and writes a create-only `agent_run` receipt.

`route` maps a workflow stage to its role, workload, provider, model profile, model request,
reasoning effort, capabilities, rationale, and routing-policy fingerprint. Independent review
routes require the author provider and fail closed when only that provider is available.
`catalog-check` validates the human review date and model floor without asserting authentication or
model access. A stale catalog exits `2` and model-based routes are forbidden until policy is reviewed.

Delegation is depth one. A delegated task cannot dispatch another agent, retry itself, approve a
gate, alter governance or live-safety files, or apply its own patch. Read-only tasks return
structured findings; implementation tasks run in a disposable worktree and return an unapplied
patch. External provider calls are serialized per workspace, while unrelated workspaces and
bounded native subagents may progress independently. Provider user settings, MCP servers, connectors, unrelated
plugins, and hooks are excluded. The caller remains responsible for reviewing, applying, testing,
and recording any change.

# Skill Contracts

The public plugin has one orchestrator and six focused skills. A skill succeeds only through
schema-backed artifacts and actual CLI results; prose is never promotion evidence.

## Shared Invariants

- No skill creates live order transport, loads trading credentials, or grants live approval.
- `live_gate` always returns forbidden in the public implementation.
- Missing evidence fails closed as `blocked`; a valid adverse research result remains recorded.
- StrategySpec and finalized package evidence are immutable. Corrections and later lifecycle
  stages create explicit new versions or superseding packages.
- A run receipt proves execution, not gate passage.
- A passed gate requires a separate v2 gate decision, exact package ID, policy hash, artifact
  fingerprints, no blockers, and a reviewer independent of the StrategySpec and run owners.
- Structured artifacts must validate before they are returned as successful output.

## Agent Delegation

The seven skills are shared by Codex and Claude Code. A host runtime may use its native bounded
subagents, while cross-provider work must pass a validated `agent_task` through `the-pass agents`.
Research and review delegation is read-only. Implementation delegation runs in a disposable Git
worktree and returns an unapplied patch. Delegation depth is one; agents cannot retry, recurse,
write protected authority paths, alter ledgers, decide a gate, or represent human approval. The
caller validates every result and remains accountable for applying and testing changes.

## Skill Matrix

| Skill | Owns | May Invoke | Must Not Do | Exit States |
| --- | --- | --- | --- | --- |
| `run` | stage selection, budgets, state, queue, stop decisions | all policy-declared contracts and focused skills | fabricate evidence, retry gates, cross live boundary | `complete`, `waiting`, `blocked`, `killed` |
| `research` | source review, hypothesis, StrategySpec | artifact validation and source tooling | use operator anecdotes as statistical proof | `research_ready`, `rejected`, `blocked` |
| `test` | data checks, features, screens, backtests, run receipt | `data`, `features`, `screen`, `backtest`, package validation, receipts | promote diagnostic fills or overwrite a prior run | `complete`, `rejected`, `revise`, `blocked` |
| `review` | independent findings, reproducibility, robustness, gate evaluation | `robustness`, `risk`, `gate`, decision ledger | edit implementation, self-review, soften blockers | `passed`, `blocked`, `revise`, `kill`, `forbidden` |
| `paper` | paper plan, isolated observation, divergence, incidents | `paper`, package supersession, receipts, prerequisite gate replay | send orders, skip windows, change original spec | `paper_ready`, `waiting`, `blocked`, `frozen` |
| `plate` | risk policy/report, config diff, approval input pack | `risk`, package supersession, receipts, prerequisite gate replay | approve live, add credentials, conceal pending decisions | `packaged`, `blocked`, `forbidden` |
| `status` | read-only state, ledger, reports, next action | `workflow status`, `receipts verify`, `report`, `dashboard` | mutate evidence, limits, or gate state | `summarized`, `blocked` |

## Run State Contract

The canonical policy is duplicated in the source distribution and repository:

- `config/skill-pipeline.v1.yaml`
- `src/the_pass/policies/skill-pipeline.v1.yaml`

The files must be byte-identical. The policy defines the seven skills, exact CLI argv contracts,
stage graph, transition and remediation budgets, target gates, and fail-closed safety settings.
`the_pass.orchestration` validates that policy and stores atomic YAML state under
`.the-pass/runs/<run-id>/state.yaml`.

A workflow can terminate `complete` only immediately after its selected target gate. It cannot
continue past that target. Resume from an existing package is allowed through preflight, but
the orchestrator revalidates all exact-package prerequisites instead of trusting the requested
start stage.

The transition counter measures work transitions and does not rewrite a verified target pass as
blocked. A workflow cannot resume after `complete`, `killed`, transition-budget exhaustion,
remediation-budget exhaustion, or two consecutive no-progress remediation laps. `waiting` and
ordinary `blocked` states require explicit resume and revalidation after their external blocker
changes.

## Independent Review

Review is separated from implementation at two layers:

1. Workflow state blocks review stages when reviewer identity is missing or equals either owner.
2. `the-pass gate evaluate` repeats that check against the actual StrategySpec and run receipt.

Research review covers chronology, source evidence, data quality, costs, fills, accounting,
selection bias, stress, risk, and clean-room reproduction. Paper review additionally covers the
predeclared window, signal/fill/cost/PnL divergence, incidents, and risk breaches. Risk review
covers exact prior gates, strategy-independent limits, config diff, monitoring, rollback, and
incident response.

Both layers may block a package. The orchestrator cannot reinterpret a blocking result as
passage.

## Immutable Progression

An experimental package is finalized before its run receipt enters the ledger. Paper and risk
artifacts are therefore not added in place. `the-pass workflow supersede --ledger <ledger>`:

1. verifies the ledger and proves the exact source package is recorded there;
2. copies it without changing source bytes;
3. removes copied local ledger and stale gate-decision files;
4. creates a new run receipt identity with source package provenance;
5. validates the target and verifies that its package ID changed.

Receipt append and ledger replay independently resolve `supersedes_package_id`, compare the exact
predecessor artifact hash, preserve strategy identity, and require a new run ID. The helper is not
the only enforcement boundary.

Package identity includes package-root paper, risk, config, approval, and gate-specific audit
evidence. The self-reference fields `risk_report.package_id` and `audit_report.package_id` are
normalized only for identity calculation; their full bytes remain ledger-fingerprinted. Gate
decisions are append-only governance attachments, excluded from package identity so they can be
recorded after the run without changing scientific evidence.

Because decisions are exact-package evidence, each successor receives fresh prerequisite gate
decisions. A paper successor must pass `research_gate` before `paper_gate`; a risk successor must
pass `research_gate` and `paper_gate` before `risk_review`.

At a target gate, remediation is legal only when an already recorded exact-package `blocked` or
`revise` decision fingerprints a schema-valid confirmed finding. A caller cannot assert progress:
`moved_gate: true` requires a new ledger-recorded successor of the current package. Append and
semantic replay reject out-of-order gate rows, duplicate package IDs at different paths, altered
predecessors, reused run IDs, and v1 evidence used as authority.

## Artifact Responsibilities

Research artifacts include `source_note`, `research_brief`, `hypothesis`, and `strategy_spec`.
Test artifacts include `instrument_registry`, `quality_report`, `feature_manifest`,
`data_manifest`, `screen_report`, `run_receipt`, `metrics_report`, and `cost_waterfall`. Review
artifacts include `findings`, `audit_report`, `verdict_report`, `risk_policy`, `risk_report`, and
`gate_decision`. Operational artifacts include `paper_plan`, `observation_manifest`,
`divergence_report`, `automation_run`, `incident_report`, `config_diff`, and `approval_pack`.

V1 compatibility artifacts such as `refire_ticket`, `simmer_laps`, and `receipt_summary` remain
readable historical evidence. They are no longer public slash-command interfaces and cannot
prove a v2 gate passage.

## Writable Boundaries

Skills may write structured evidence under `research/`, `experiments/`, `reports/`, and local
`.the-pass/` workflow state. Repository maintenance may also update `docs/`, `schemas/`,
`templates/`, `config/`, and public-safe examples.

Skills must never write secrets, paid datasets, private account data, broker live configuration,
or real order-placement code without a separately accepted live-capability ADR and explicit user
instruction. No such path exists in this version.

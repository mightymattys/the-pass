# The Pass Commands

The Codex and Claude Code plugins expose the same seven public skills. `/the-pass:run` is the
whole-line front door; the other six commands are focused stations that it may invoke. The Python
CLI remains the validation and state-transition authority.

## Public Commands

| Command | Inputs | Required Output | Exit States |
| --- | --- | --- | --- |
| `/the-pass:run <objective>` | objective, optional package, target gate, owners, budgets | resumable workflow state, artifacts, receipts, gate decisions | complete, waiting, blocked, killed |
| `/the-pass:research <topic>` | topic, source, hypothesis, or draft spec | reviewed source notes, hypothesis, immutable StrategySpec version | research_ready, rejected, blocked |
| `/the-pass:test <spec>` | StrategySpec, data evidence, optional test mode | screen report or complete reproducible run package | complete, rejected, revise, blocked |
| `/the-pass:review <package>` | exact package, target gate, independent reviewer | findings, audit evidence, gate decision | passed, blocked, revise, kill, forbidden |
| `/the-pass:paper <candidate>` | exact research-gated package and paper policy | successor package, paper plan, observations, divergence evidence | paper_ready, waiting, blocked, frozen |
| `/the-pass:plate <candidate>` | exact paper-gated package | risk evidence, config diff, approval pack, successor package | packaged, blocked, forbidden |
| `/the-pass:status [run]` | workflow state, ledger, repo, or strategy filter | concise state and next-action summary | summarized, blocked |

## Whole-Line Run

`/the-pass:run` accepts one bounded target:

- `research_gate` for a new idea or an unfinished research package;
- `paper_gate` for a package whose strategy should be observed in the isolated paper process;
- `risk_review` for a paper-gated package that needs a complete approval input pack.

If the target is omitted, the command selects the earliest unpassed gate supported by exact
package evidence. It does not infer passage from filenames, prose, verdict labels, or v1 ledger
entries. `live_gate` is not a valid target.

The deterministic queue is:

```text
preflight
  -> research -> screen -> backtest -> robustness -> review_research -> research_gate
  -> paper_prepare -> paper_observe -> review_paper -> paper_gate
  -> risk_prepare -> plate -> review_risk -> risk_review
  -> complete
```

The run may enter `remediation` only for a concrete finding. It stops after three remediation
laps, after two consecutive no-progress laps, or after twenty total transitions. It also stops
when a paper window is incomplete, evidence is unavailable, a kill condition fires, or an
independent reviewer is absent. A blocked state resumes only through an explicit `--resume`
transition after its blocker has been resolved and external evidence revalidates.
Entering remediation requires at least one existing `--evidence` path. The runtime derives
remediation accounting from the destination stage, and `--moved-gate` defaults to `false` so an
omitted flag cannot reset the no-progress counter. At a target gate, entry also requires a
ledger-recorded `blocked` or `revise` decision whose exact package fingerprints a confirmed
blocking finding. `--moved-gate true` is accepted only with a new recorded successor package.
Budget exhaustion and two consecutive no-progress laps are non-resumable; continuation requires a
new bounded workflow rather than editing counters or leaving the blocked remediation stage.
`waiting` is resumable only when the declared external condition has changed. `killed`,
`complete`, transition-budget exhaustion, remediation-budget exhaustion, and no-progress
exhaustion are terminal for that workflow ID.

State is stored at `.the-pass/runs/<run-id>/state.yaml`. Every transition is atomic and contains
the current stage, target, owners, reviewer, exact package ID, evidence paths, blockers, budgets,
and next action. Finalized scientific and operational evidence is never edited: later paper or
risk evidence uses a superseding package with a new run receipt and package ID. Gate decisions
are separate append-only governance attachments and cannot be overwritten or retried.

For mechanically supervised execution, inspect first and then explicitly enable the local driver:

```bash
the-pass workflow execute --state <path> --author-provider codex \
  --format json --driver auto
the-pass workflow execute --state <path> --author-provider codex \
  --execute --format json --driver auto
```

The supervisor invokes one stage per cycle, validates a new checkpoint, and refuses success from
an unchanged or intermediate state. `auto` selects the provider and model through the versioned
stage policy. A custom trusted driver command may replace `auto`; `--driver` must be the final
option because all remaining tokens are the driver argv.

## Shared Rules

- Native runtime subagents may be used within their declared read/write restrictions. Cross-runtime
  work must use `the-pass agents inspect` and an explicit `agents dispatch --execute` call.
- Delegation depth is one. Delegated agents cannot spawn another provider task or recursively invoke
  the coordinator.
- External provider calls are serialized per local user. Parallel work uses bounded native
  subagents inside the active provider call.
- Broker-managed providers run without user/project MCP servers, connectors, unrelated plugins,
  hooks, rules, or provider-native multi-agent features.
- Cross-provider tasks use structured workload/model profiles. The policy may raise a requested
  profile to satisfy role, write-mode, or native-subagent capability floors; task text cannot name
  an arbitrary model.
- Read-only delegates return evidence only. Write delegates return an unapplied worktree patch; the
  caller reviews and applies it.
- No agent may write gate decisions, approval state, ledgers, orchestration policy, protected safety
  code, credentials, or live paths. Agent output is never human approval or gate passage.
- Every promotion claim comes from a valid v2 `gate_decision` for the exact package ID.
- A reviewer must be named and differ from both the StrategySpec owner and run owner.
- Every finalized run is added to the ledger, including `kill`, `revise`, and `blocked` results.
- Authoritative evidence is a v2 run recorded for the exact resolved package path. V1 rows,
  byte-identical copies, and duplicate package IDs at another path cannot authorize progression.
- A gate decision must follow its run in ledger order and every successor must replay prerequisite
  gates on its own package ID.
- Gate decisions are never automatically retried.
- The runner may invoke only CLI contracts declared in `config/skill-pipeline.v1.yaml`.
- Missing capability or evidence produces `blocked`; an incomplete observation window produces
  `waiting`.
- Real order transport, trading credentials, authenticated order channels, and live approval are
  forbidden in the public workflow.

## Machine Interface

The workflow state API is additive to the existing research CLI:

```bash
the-pass workflow start --state <path> --run-id <id> --objective <text> \
  --target-gate research_gate --strategy-owner <owner> --run-owner <owner> \
  --ledger <path>
the-pass workflow advance --state <path> --to-stage <stage> \
  --status in_progress --next-action <text>
the-pass workflow status --state <path>
the-pass workflow execute --state <path> [--execute] --driver auto|<trusted argv>
the-pass workflow fingerprint <package>
the-pass workflow supersede <source-package> <target-package> \
  --ledger <ledger> --run-id <new-id> --created-at <RFC3339>
the-pass agents route --stage <stage> [--author-provider codex|claude]
```

The orchestrator maps stages only to the exact parser contracts in
`config/skill-pipeline.v1.yaml`. Core evidence commands include `data`, `features`, `screen`,
`backtest`, `robustness`, `risk`, `paper`, `gate`, `receipts`, `report`, and `dashboard`.

All machine responses follow [CLI_CONTRACT.md](../public/CLI_CONTRACT.md). Exit `0` means a
successful operation or passed gate; `1` is invalid input or technical failure; `2` is a valid
non-promoted state; `3` is forbidden by the safety boundary.

See [SKILL_CONTRACTS.md](../implementation/SKILL_CONTRACTS.md) for implementation-level
ownership and evidence requirements.

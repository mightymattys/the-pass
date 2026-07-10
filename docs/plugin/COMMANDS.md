# The Pass Commands

The plugin exposes seven public skills. `/the-pass:run` is the whole-line front door; the other
six commands are focused stations that it may invoke. The Python CLI remains the validation and
state-transition authority.

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

State is stored at `.the-pass/runs/<run-id>/state.yaml`. Every transition is atomic and contains
the current stage, target, owners, reviewer, exact package ID, evidence paths, blockers, budgets,
and next action. Finalized scientific and operational evidence is never edited: later paper or
risk evidence uses a superseding package with a new run receipt and package ID. Gate decisions
are separate append-only governance attachments and cannot be overwritten or retried.

## Shared Rules

- Every promotion claim comes from a valid v2 `gate_decision` for the exact package ID.
- A reviewer must be named and differ from both the StrategySpec owner and run owner.
- Every finalized run is added to the ledger, including `kill`, `revise`, and `blocked` results.
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
the-pass workflow fingerprint <package>
the-pass workflow supersede <source-package> <target-package> \
  --run-id <new-id> --created-at <RFC3339>
```

The orchestrator maps stages only to the exact parser contracts in
`config/skill-pipeline.v1.yaml`. Core evidence commands include `data`, `features`, `screen`,
`backtest`, `robustness`, `risk`, `paper`, `gate`, `receipts`, `report`, and `dashboard`.

All machine responses follow [CLI_CONTRACT.md](../public/CLI_CONTRACT.md). Exit `0` means a
successful operation or passed gate; `1` is invalid input or technical failure; `2` is a valid
non-promoted state; `3` is forbidden by the safety boundary.

See [SKILL_CONTRACTS.md](../implementation/SKILL_CONTRACTS.md) for implementation-level
ownership and evidence requirements.

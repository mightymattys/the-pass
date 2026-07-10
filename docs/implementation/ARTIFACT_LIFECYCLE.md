# Artifact Lifecycle

The Pass is artifact-first. A strategy only moves forward when the required files exist,
validate, and support the gate claim.

## Lifecycle

```text
source -> source_note -> hypothesis -> StrategySpec -> screen -> backtest package
       -> independent review -> research gate -> paper successor -> paper gate
       -> risk successor -> risk review -> receipts and read-only reports
```

`/the-pass:run` coordinates this line. `/the-pass:research`, `/the-pass:test`,
`/the-pass:review`, `/the-pass:paper`, and `/the-pass:plate` own focused stages;
`/the-pass:status` reads state and evidence without mutating them.

## Artifact Ownership

| Stage | Primary Artifact | Created By | Mutable? | Promotion Use |
| --- | --- | --- | --- | --- |
| Source review | `source_note` | `research` | yes until reviewed | Required for source-backed claims |
| Hypothesis | `hypothesis` | `research` | yes before StrategySpec | Bridges claims to falsifiable tests |
| Strategy definition | `StrategySpec` | `research` | yes before first run | Required for all runs |
| Data evidence | `data_manifest` | `test` or adapter | no after run | Required for every run |
| Run evidence | `run_receipt` | runner or `test` | no after run | Required for every run |
| Performance evidence | `metrics_report` | runner or `test` | no after run | Required for verdict |
| Cost evidence | `cost_waterfall` | runner or `test` | no after run | Required for verdict |
| Decision | `verdict_report` | `review` | append/supersede | Required for gate |
| Review findings | `findings`, `audit_report` | `review` | append/supersede | Explains independent gate result |
| Remediation state | workflow state and successor receipt | `run` | append/supersede | Constrains confirmed fixes and budgets |
| Paper plan | `paper_plan` | `paper` | no after observation starts | Required for paper observation |
| Paper evidence | `observation_manifest`, `divergence_report` | `paper` | append/supersede | Required for risk review |
| Approval evidence | `approval_pack` | `plate` | append/supersede | Human decision input only |
| Gate decision | `gate_decision` | `review` through gate evaluator | append-only | Only artifact that can prove a passed gate |
| Ledger | receipt index | CLI, summarized by `status` | append-only | Required for audit |

## Package Layout

Strategy-level artifacts live one directory above individual runs:

```text
experiments/runs/<strategy-id>/
  strategy_spec.yaml
  source_note.yaml
```

Each run package copies its `strategy_spec` and cited source notes from the strategy-level
directory. The copies keep the package self-contained because `the-pass validate-package`
requires `strategy_spec` inside the package directory.

Recommended run package:

```text
experiments/runs/<strategy-id>/<run-id>/
  source_notes/
  strategy_spec.yaml
  data_manifest.yaml
  run_receipt.yaml
  metrics_report.yaml
  cost_waterfall.yaml
  verdict_report.yaml
  findings.yaml            # required for paper_candidate
  logs/
```

Generated outputs should not overwrite prior run packages. A rerun creates a new `run-id`
and links to the previous package in its receipt. Paper and risk phases always create a
superseding package because the source run has already been receipted. The supersede command
requires that shared ledger and refuses unrecorded or altered source packages. The same lineage
checks run during ordinary receipt append and full semantic replay, so manually authored
`supersedes_*` fields cannot bypass the helper.

V1 rows remain readable historical evidence but are never authoritative for package identity,
lineage, promotion, remediation, or completion. Every authoritative lookup requires the exact
recorded package path as well as its v2 package ID and artifact fingerprints.

## Immutability Rules

- Raw data is immutable.
- Normalized data is derived and must reference raw fingerprints.
- Run receipts are append-only.
- Metrics and cost reports are immutable after the verdict is recorded.
- A revised StrategySpec must create a new version before rerun.
- A corrected artifact supersedes the old artifact; it does not silently replace it.
- A successor package receives a new package ID and must pass exact-package prerequisite gates
  again before the next gate is evaluated.
- Paper, risk, config, approval, and gate-specific audit artifacts participate in package
  identity. Gate decisions are separate append-only governance attachments and do not.

## Receipt Ledger

The receipt ledger is JSONL and append-only. Each entry records the package path, relative
artifact paths, SHA-256 fingerprints, strategy ID, run ID, gate, verdict, cost report, data
manifest, open blockers, `previous_hash`, and `entry_hash`.

`the-pass receipts add` validates and records a run without claiming that a gate passed.
`the-pass gate evaluate` creates a separate artifact-backed decision, and
`the-pass receipts add-decision` records it. `the-pass receipts verify` recomputes the hash
chain, resolves every recorded artifact, rebuilds v2 runs, and replays v2 gate decisions against
the bundled policy in ledger order. A later gate may trust only an earlier decision that passed
this replay. Legacy v1 entries remain readable but cannot prove a v2 promotion.

## Gate Inputs

Research gate requires:

- Reviewed source notes or explicit synthetic/example marker.
- Complete StrategySpec.
- Data manifest.
- Run receipt.
- Metrics report.
- Cost waterfall.
- Verdict report.

Paper gate additionally requires:

- Paper plan.
- Observation manifest.
- Paper-vs-backtest divergence policy.
- Risk review checklist.

Live decision pack additionally requires:

- An explicit pending human approval decision with a named owner. The pack cannot approve it.
- Exact config hash.
- Adapter and venue.
- Credential boundary.
- Dry-run proof.
- Rollback plan.
- Incident runbook.

## Verdict States

- `kill`: stop this hypothesis.
- `revise`: fix spec, data, cost, or execution assumptions and rerun.
- `paper_candidate`: evidence is strong enough for paper/replay only.
- `blocked`: missing evidence or unresolved safety issue.

No verdict can approve live trading.

The screen workflow's `backtest_candidate` is a `screen_report.decision.status` exit state.
It is not a `verdict_report.verdict` value.

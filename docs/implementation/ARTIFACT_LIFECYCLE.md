# Artifact Lifecycle

The Pass is artifact-first. A strategy only moves forward when the required files exist,
validate, and support the gate claim.

## Lifecycle

```text
source -> source_note -> hypothesis -> StrategySpec -> screen -> backtest package
       -> taste -> refire/simmer -> paper -> plate -> receipts
```

## Artifact Ownership

| Stage | Primary Artifact | Created By | Mutable? | Promotion Use |
| --- | --- | --- | --- | --- |
| Source review | `source_note` | `research` | yes until reviewed | Required for source-backed claims |
| Hypothesis | `hypothesis` | `research` | yes before StrategySpec | Bridges claims to falsifiable tests |
| Strategy definition | `StrategySpec` | `spec` | yes before first run | Required for all runs |
| Data evidence | `data_manifest` | `backtest` or adapter | no after run | Required for every run |
| Run evidence | `run_receipt` | runner or skill | no after run | Required for every run |
| Performance evidence | `metrics_report` | runner or skill | no after run | Required for verdict |
| Cost evidence | `cost_waterfall` | runner or skill | no after run | Required for verdict |
| Decision | `verdict_report` | `taste` or gate skill | append/supersede | Required for gate |
| Review findings | `findings` | `taste` | append/supersede | Explains independent gate result |
| Repair scope | `refire_ticket` | `taste` or `refire` | append/supersede | Constrains confirmed fixes |
| Paper plan | `paper_plan` | `paper` | no after observation starts | Required for paper observation |
| Paper evidence | `observation_manifest`, `divergence_report` | `paper` | append/supersede | Required for risk review |
| Approval evidence | `approval_pack` | `plate` | append/supersede | Human decision input only |
| Ledger | receipt index | `receipts` | append-only | Required for audit |

## Package Layout

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
and may link to the previous package in its receipt.

## Immutability Rules

- Raw data is immutable.
- Normalized data is derived and must reference raw fingerprints.
- Run receipts are append-only.
- Metrics and cost reports are immutable after the verdict is recorded.
- A revised StrategySpec must create a new version before rerun.
- A corrected artifact supersedes the old artifact; it does not silently replace it.

## Receipt Ledger

The receipt ledger is JSONL and append-only. Each entry records the package path, relative
artifact paths, SHA-256 fingerprints, strategy ID, run ID, gate, verdict, cost report, data
manifest, open blockers, `previous_hash`, and `entry_hash`.

`the-pass receipts add` validates a package before appending it. `the-pass receipts verify`
recomputes the hash chain, resolves every recorded package artifact, and fails if a receipt
or referenced artifact was edited, removed, or moved silently.

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

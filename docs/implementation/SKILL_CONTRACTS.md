# Skill Contracts

Each skill is a product interface. It should produce structured artifacts or explicit
blockers, not only prose.

## Shared Rules

- Never create real order placement paths.
- Never write secrets or credentials.
- Prefer public-safe examples.
- If required evidence is missing, return `blocked`.
- Every gate claim must cite artifacts.
- Every structured output must validate against the matching schema before its success state
  can be returned.
- Gate IDs use lower snake case; core gates are `research_gate`, `paper_gate`, `risk_review`,
  and `live_gate`.

## Contracts

| Skill | Inputs | Writes | Must Check | Exit States |
| --- | --- | --- | --- | --- |
| `mise` | repo path | setup docs, folders, missing templates | plugin manifest, ADRs, public safety, schemas | ready, repaired, blocked |
| `research` | topic or source URL/content | source notes, hypothesis artifacts | source type, claim, evidence, limitations, required tests | reviewed, rejected, blocked |
| `spec` | idea or hypothesis | `StrategySpec` | edge thesis, data needs, costs, risks, done/kill criteria | draft, research_ready, blocked |
| `screen` | StrategySpec, optional data manifest | screen report | diagnostic-only assumptions, null baseline, costs | reject, revise, backtest_candidate, blocked |
| `backtest` | StrategySpec, data manifest, runner config | run package | manifest, receipt, metrics, cost waterfall, safety flags | complete, blocked |
| `taste` | run package | verdict report, findings | leakage, overfit, costs, fills, risk, reproducibility | pass, blocked, revise, kill |
| `refire` | confirmed findings | patch or superseding artifacts | scope boundaries, verification evidence | fixed, still_blocked |
| `simmer` | target gate, package | iteration receipts | one target gate, no-progress, kill limits | passed, blocked, killed |
| `paper` | paper candidate package | paper plan, observation checklist | same decision logic, divergence policy, no real orders | paper_ready, blocked |
| `plate` | paper/risk package | approval pack | exact config hash, limits, rollback, unresolved risk | packaged, blocked |
| `receipts` | repo or strategy ID | ledger summary | artifact links, verdicts, costs, blockers | summarized, blocked |

## Editable Paths

Skills may write:

- `docs/`
- `templates/`
- `schemas/`
- `research/`
- `experiments/`
- `reports/`
- `examples/`

Skills must not write:

- credential files,
- private data files,
- paid data dumps,
- broker/exchange live configs,
- live order placement code without accepted live ADR.

## Required Evidence For Promotion

`taste` can pass a package only when:

- The package validates.
- Gross and net metrics are both present.
- Cost waterfall exists.
- Data manifest exists and names limitations.
- Null/random baseline exists or absence is justified.
- Execution assumptions are explicit.
- Safety flags say live trading is disabled and real order path is unavailable.

`pass` is the `taste` command state. At `research_gate`, the matching
`verdict_report.verdict` is `paper_candidate`, not `pass`.
`research_ready` is the `spec` command state; the matching StrategySpec state is `research`.

`paper` can recommend risk review only when:

- Backtest package passed `taste`.
- Paper observation plan uses the same decision logic or documents every difference.
- Divergence thresholds are set before observation.

`plate` can package evidence only. It cannot grant live approval.

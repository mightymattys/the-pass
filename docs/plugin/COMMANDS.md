# The Pass Commands

The Pass uses kitchen-language commands because the product is a review station. Strategy
ideas are recipes; evidence is the plate; gates decide whether anything leaves the line.

The plugin manifest supplies the `the-pass` namespace. Each skill's internal name is the plain
folder name (`mise`, `research`, and so on), which Codex exposes as `/the-pass:<skill>`.

## Commands

| Command | Inputs | Required Output | Exit States |
| --- | --- | --- | --- |
| `/the-pass:mise` | repo path | setup audit or repaired scaffold | ready, repaired, blocked |
| `/the-pass:research <topic>` | topic, URL, file, or source text | source notes and hypothesis artifacts | reviewed, rejected, blocked |
| `/the-pass:spec <idea>` | idea or hypothesis | `StrategySpec` | draft, research_ready, blocked |
| `/the-pass:screen <spec>` | StrategySpec and optional data manifest | diagnostic screen report | reject, revise, backtest_candidate, blocked |
| `/the-pass:backtest <spec>` | StrategySpec, data manifest, runner config | run package | complete, blocked |
| `/the-pass:taste <run>` | run package | verdict and findings | pass, blocked, revise, kill |
| `/the-pass:refire <findings>` | confirmed findings | patch or superseding artifacts | fixed, still_blocked |
| `/the-pass:simmer <gate>` | target gate and package | iteration receipts | passed, blocked, killed |
| `/the-pass:paper <candidate>` | tasted package | paper plan | paper_ready, blocked |
| `/the-pass:plate <candidate>` | paper/risk package | approval pack | packaged, blocked |
| `/the-pass:receipts` | repo or strategy ID | ledger summary | summarized, blocked |

## Shared Command Rules

- Commands write structured artifacts where possible.
- Commands cannot grant live approval.
- Commands cannot hide missing evidence behind prose.
- Commands must return `blocked` when required artifacts or safety evidence are missing.
- Commands must preserve previous run packages instead of overwriting them silently.
- Gate IDs use lower snake case. The canonical IDs are `research_gate`, `paper_gate`,
  `risk_review`, and `live_gate`.

`taste` uses `pass` as a command exit state. A passed `research_gate` writes
`paper_candidate` to the core verdict artifact; later gates use their own schema-backed
workflow artifacts. No core verdict means live approval.

`spec` uses `research_ready` as a command exit state; its matching artifact state is
`StrategySpec.status: research`.

## Live Boundary

No command sends real orders. `plate` can prepare an approval pack, but live approval must
be explicit, dated, human-controlled, and tied to an exact config hash.

See [../implementation/SKILL_CONTRACTS.md](../implementation/SKILL_CONTRACTS.md) for the
implementation-level contract.

## Implemented CLI

The first concrete CLI commands are artifact validators:

```bash
the-pass validate <artifact>
the-pass validate-package <run-dir>
the-pass validate <adapter.yaml> --type adapter
the-pass receipts add <run-dir>
the-pass receipts verify
the-pass receipts
```

They accept JSON or YAML, infer all core and workflow artifact types where possible, and
return non-zero on missing or weak evidence. Receipt commands maintain an append-only,
hash-chained JSONL ledger and verify referenced artifact fingerprints.

---
name: test
description: "Test a validated StrategySpec through canonical data checks, deterministic features, preregistered screening, and event-driven backtesting in screen, backtest, or automatic mode."
---

# The Pass Test

Use this skill to turn a research-ready StrategySpec into diagnostic screen evidence or a complete
immutable backtest package.

## Inputs

- Valid StrategySpec and owner/run owner identities.
- Canonical events or approved public-safe fixture, data manifest, and quality policy.
- Preregistered parameter space, cost model, fill model, latency assumptions, random seed, and
  selected mode: `screen`, `backtest`, or `auto`.
- Shared ledger path and new package path.

## Read First

- `templates/quality_report.yaml`
- `templates/feature_manifest.yaml`
- `templates/screen_report.yaml`
- `templates/data_manifest.yaml`
- `templates/run_receipt.yaml`
- `templates/metrics_report.yaml`
- `templates/cost_waterfall.yaml`
- `templates/verdict_report.yaml`
- `docs/adapters/DATA_FOUNDATION.md`
- `docs/implementation/BACKTEST_HARNESS.md`
- `docs/implementation/ARTIFACT_LIFECYCLE.md`

## Editable Paths

- New diagnostics under `experiments/screens/<screen-id>/` and `reports/screens/`.
- New packages under `experiments/runs/<strategy-id>/<run-id>/`.
- Public-safe normalized/feature outputs approved for the run.
- Append-only entries in the selected ledger after package finalization.

## Blocked Paths

- Raw paid/private data, credentials, live adapters, real order paths, and recorded packages.
- StrategySpec thesis, kill conditions, or preregistered search space after results are visible.
- Promotion gate decisions; `/the-pass:review` owns them.

## Agent Delegation

- A native implementer or cross-provider `implementer` may prepare a scoped change in an isolated
  worktree under `docs/plugin/CROSS_RUNTIME.md`.
- The result must be an unapplied patch limited to the task allowlist. The caller inspects it and
  reruns data, package, lint, and test checks after application.
- Do not delegate edits to gate policy, ledgers, orchestration policy, live paths, or immutable
  evidence. A delegate cannot promote its own test result.

## Procedure

### Shared preflight

- Validate StrategySpec and require a valid, unblocked quality report before testing.
- Require deterministic event ordering and `receive_time <= decision_time` availability.
- Record the full search space before running any variant.
- Use explicit fees, spread, slippage, latency, impact, funding/borrow/roll, and missed fills.

### Screen mode

- Build deterministic features when required and run every preregistered variant.
- Screens are diagnostic only. Mid-price and bar-close assumptions must be labeled accordingly.
- Compare gross and net results with a null/random baseline.
- Return `backtest_candidate` internally only when evidence survives conservative costs and has a
  plausible event-simulation path. Public skill exit remains `complete`.
- `reject`, `revise`, and `blocked` never auto-escalate.

### Backtest mode

- Require a prior `backtest_candidate` screen unless an artifact-backed exception exists.
- Use the reference baseline CLI only when the strategy family is supported; otherwise use an
  external engine behind the same package contracts.
- Produce StrategySpec copy, source notes, data and feature manifests, quality report, search
  space, run receipt, metrics, cost waterfall, verdict, and static reports.
- Check portfolio conservation and gross-to-net reconciliation after simulation.
- Finalize before ledger append. Every valid blocked or killed run is still recorded.

### Auto mode

- Run screen first. Advance to backtest only on a validated `backtest_candidate` decision.
- Stop on reject, revise, blocked quality, or unsupported fill evidence.

## Required Checks

Use the implemented CLI when its capability predicate fits:

```bash
the-pass data quality <events> --dataset-id <id> --created-at <rfc3339> --output <quality>
the-pass features build <events> --dataset-fingerprint <sha256> --code-version <version> \
  --config <config-json> --created-at <rfc3339> --output-dir <features-dir>
the-pass screen run --closes <closes-json> --variants <variants-json> \
  --family <family> --fee-bps <bps> --output <screen-results>
the-pass backtest baseline --name <baseline> --output <new-package>
```

Finalize and record:

```bash
the-pass validate <screen-report> --type screen_report
the-pass validate-package <package>
the-pass receipts add <package> --ledger <ledger>
the-pass receipts verify --ledger <ledger>
```

## Outputs

- Quality and feature evidence.
- Complete screen report with all attempted variants.
- Complete immutable backtest package when mode reaches backtest.
- Verified run receipt entry, exact verdict, blockers, and next action.

## Exit States

- `complete`: requested screen/backtest work validates and every final package is recorded.
- `rejected`: diagnostic or backtest evidence fails its predefined baseline or kill condition.
- `revise`: a fixable spec, data, cost, execution, or implementation problem requires a new run.
- `blocked`: required data, quality, timing, execution, owner, package, or ledger evidence is missing.

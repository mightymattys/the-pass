# Trading Roadmap Execution Plan

Status: active.
Approved: 2026-07-10.

This plan turns The Pass from a public artifact framework into an engine-neutral research
operating system for crypto, futures, and prediction markets. Milestones are gate-ordered:
H0 -> R0 -> D1 -> B2 -> V3 -> P4 -> L5/L6. A later milestone must not be marked complete
before its dependency has passed. The machine-readable source of status is
`roadmap-status.yaml`.

## Completion Rule

A framework milestone is complete only when all deliverables and acceptance tests exist,
its capability gate result is `pass`, evidence paths are recorded, no P0/P1 finding remains,
and CI is green. Candidate promotion gates are separate evidence states and may remain
blocked or killed without making the testing repository incomplete. Profitability and the
existence of a promoted strategy are not framework completion criteria.

Roadmap statuses are `not_started`, `in_progress`, `blocked`, `gate_failed`, and
`complete`. `blocked` means evidence required to build or verify the framework capability is
missing. `gate_failed` means the capability evidence was evaluated and failed. Candidate
gate state is stored separately. A complete milestone needs a machine-readable capability
gate record whose acceptance checks all pass and whose evidence paths exist.
`scripts/validate_roadmap.py` enforces this rule.

## Milestone Contracts

| Milestone | Required inputs | Required outputs | Acceptance evidence |
| --- | --- | --- | --- |
| H0 | v1 schemas, plugin skills, synthetic packages, prior audit findings | v2 ledger and gate decision, stricter validators, regression tests | `reports/gates/H0_2026-07-10.yaml` |
| R0 | reviewed primary sources, operator material, OxfordStrat backlog | source registry, source notes, research brief, five StrategySpecs and Oxford hypotheses | `reports/gates/R0_2026-07-10.yaml` |
| D1 | frozen event and adapter contracts, public read-only endpoints, futures fixture | canonical data, quality and feature manifests, immutable storage, three adapter lanes | `reports/gates/D1_2026-07-10.yaml` |
| B2 | valid unblocked data manifest and quality report, preregistered search spaces | screen results, deterministic simulator results, complete run packages, ledgers and static reports | `reports/gates/B2_2026-07-10.yaml` |
| V3 | B2 packages, full strategy zoo, asset-specific policy thresholds | robustness, stress, risk and independent audit evidence with clean replay | `reports/gates/V3_2026-07-10.yaml` |
| P4 | canonical synthetic package plus read-only observer contracts | isolated paper journal, divergence report, automation receipts, incidents and static dashboard | `reports/gates/P4_2026-07-10.yaml` |
| L5/L6 | public safety requirements and dry-run contracts | a tested locked boundary with no order transport or credentials | `reports/gates/L5_L6_2026-07-10.yaml` |

Every milestone owner is accountable for its inputs, outputs, acceptance tests, gate
record, kill condition, and evidence paths. The owner cannot waive an independent reviewer
or alter risk policy from strategy code.

## H0: Framework Trust

Owner: automation_engineer.

Build:

- Separate immutable run receipts from promotion decisions.
- Add v2 ledger entries with `entry_kind: run|gate_decision` and preserve v1 read support.
- Add `gate_decision`, versioned gate policies, `the-pass gate evaluate`, and
  `the-pass receipts add-decision`.
- Restrict core gates to `research_gate`, `paper_gate`, `risk_review`, and `live_gate`.
- Fix chronology, promotion metrics, PBO/PSR bounds, gross-to-net consistency, and workflow
  no-progress validation.
- Keep every valid run in the ledger, including blocked, revise, and kill outcomes.

Gate:

- A blocked run cannot be represented as a passed paper gate.
- Reversed sample or holdout windows fail.
- Promotion cannot pass with only PnL populated.
- Any pair of consecutive no-progress remediation laps fails.
- V1 evidence remains readable but cannot prove a v2 promotion.

Kill: stop later work if a gate can still pass from labels instead of artifact evidence.

## R0: Research Operating System

Owner: head_researcher.

Build:

- Curated `research/sources.yaml` registry and structured source notes.
- At least 20 reviewed sources across overfitting, validation, execution, futures/trend,
  crypto/perpetuals, investor/operator process, and OxfordStrat baselines.
- `research_brief` and `audit_report` artifact contracts.
- Five initial StrategySpecs: random control, spot buy-and-hold, spot momentum, diversified
  futures trend, and prediction-market complement/fair-value.
- Grow to 50 structured sources, at least 30 reviewed, before V3 completes.

Gate: 20 reviewed notes, five valid specs, explicit evidence classification, and no live
code.

Kill: rewrite the research method if source claims cannot become falsifiable tests.

## D1: Canonical Data and Adapters

Owner: data_steward.

Build:

- Lossless `Instrument`, `CanonicalEvent`, `InstrumentRegistry`, `QualityReport`, and
  `FeatureManifest` contracts.
- Immutable Parquet raw partitions, derived normalized/features stores, DuckDB queries,
  atomic writes, fingerprints, and deterministic event ordering.
- Quality checks for intervals, duplicates, timestamp order, sequences, prices, books,
  outliers, sessions, rolls, and truncation.
- A provider-neutral adapter protocol for discovery, raw fetch, normalization, cross-check,
  manifest, cost snapshot, and optional settlement snapshot.
- Parallel read-only adapter lanes: Binance Spot, Databento-compatible futures, and
  Polymarket market data. Licensed futures data is never redistributed.

Gate: all three adapter contracts pass; Binance and Polymarket pass public read-only smoke;
futures passes fixture replay; normalization and features are deterministic.

Kill: block a provider if timestamps, licensing, or source semantics are unreliable.

## B2: Screen and Backtest Harness

Owner: strategy_implementer.

Build:

- Engine-neutral strategy, feature, cost, fill, portfolio, risk, and result interfaces.
- NumPy/pandas diagnostic screening and a deterministic event-driven reference simulator.
- Conservative market/limit fills, partial fills, depth, queue, latency, rejected orders,
  and asset-specific costs.
- Buy-and-hold, seeded random, momentum/Donchian, volatility-filtered mean reversion,
  futures trend, and prediction-market structural baselines.
- Complete artifact packages plus JSON, Markdown, and static HTML reports for every run.

Gate: four core baselines run, random has no systematic net edge, accounting invariants
hold, every run has a cost waterfall, and all variants are ledgered.

Kill: stop research if known baseline behavior cannot be reproduced.

## V3: Robustness, Risk, and Audit

Owner: stats_auditor.

Build:

- Anchored/rolling walk-forward, purging, embargo, CSCV/PBO, PSR/DSR, deterministic
  bootstrap, regimes, sensitivity, and Reality Check/SPA where applicable.
- Versioned asset-class policies and standard fee, slippage, latency, depth, fill, funding,
  outage, and correlated-gap stresses.
- Independent `RiskPolicy` and `RiskReport` with sizing, drawdown distribution, expected
  shortfall, risk-of-ruin proxy, correlation, scenarios, and capacity.
- Independent findings and clean-directory receipt reproduction.

Gate: every paper candidate has OOS/walk-forward evidence, relevant PBO/DSR, stress,
sensitivity, risk report, independent review, and reproducible outputs.

Kill: stop if the ledger omits losing trials or robustness depends on one narrow parameter.

## P4: Paper, Automation, and Reporting

Owner: automation_engineer.

Build:

- Read-only Binance and Polymarket observers and licensed-data-only futures observer.
- A virtual paper broker using the same decision code, event schema, and config hash as
  backtest, with no live trading client.
- Decision journal, simulated intents/fills, risk events, outages, and divergence reports.
- Scheduler-neutral `AutomationSpec`, `AutomationRun`, and `IncidentReport`; external cron
  or CI invokes idempotent jobs.
- Read-only static research, experiment, robustness, cost, risk, divergence, incident, and
  receipt dashboards.

Candidate gate policy implemented by this milestone:

- Crypto: 30 days and 100 fills or 500 signals, realized costs within 25% of model.
- Futures: 60 trading days or 30 trades, whichever is later.
- Prediction markets: 1,000 paper-ready signals unless an accepted ADR lowers the limit.
- No unresolved data/risk incident and no retrospective StrategySpec rewrite.

Kill: return to execution research if paper fills or costs materially diverge.

## L5/L6: Locked Live Boundary

Owner: risk_officer.

Only public contracts for an execution gateway, human decision, config diff, dry-run proof,
and live risk evidence may be designed. No real order transport, authenticated order client,
or credential loader may be implemented without a new explicit user instruction and an
accepted venue-specific live-capability ADR, threat model, legal/provider review, credential
boundary, and dry-run proof.

The default future micro-live envelope is the lower of USD 100 or 0.25% of approved equity,
the lower of USD 25 or 0.10% equity daily loss, and at most 1x leverage. L6 requires TCA,
adverse-selection review, a fixed trade-count review, and paper/live tolerance evidence.

## Public Interfaces and Compatibility

- Schema dispatch is by `(artifact_type, schema_version)`.
- V1 remains readable; new templates and promotion evidence use v2.
- New artifacts: gate decision, research brief, audit report, instrument registry, quality
  report, feature manifest, risk policy/report, automation spec/run, incident report, and a
  locked human decision.
- New CLI groups: data, features, screen, backtest, robustness, risk, gate, paper, report,
  dashboard, automation, incident, and receipts.
- All commands support text and stable JSON output. Exit codes: 0 success/pass, 1 invalid or
  technical failure, 2 valid blocked/revise/kill, 3 forbidden safety action.
- Base install stays light; optional extras are data, research, paper, and dev.
- Python 3.9 and 3.12 remain supported. Default CI is offline; network smoke is opt-in.

## Promotion Gate Semantics

- `research_gate` requires a valid v2 package, `paper_candidate` verdict, independent
  findings, a research/paper-capable adapter, reviewed source notes, and no blocker.
- `paper_gate` requires a passed research gate for the exact package ID, a paper-ready plan,
  observation manifest, completed elapsed and count minimums, a `risk_review_candidate`
  divergence report, and no blocking breach.
- `risk_review` requires a passed paper gate for the exact package ID, an unblocked passing
  risk report, packaged approval evidence, config diff, matching config hash, limits,
  monitoring, rollback, and incident plans.
- `live_gate` always returns blocked with exit code 3. Neither an agent nor an approval pack
  can grant live approval in the public repository.

A run is immutable evidence regardless of `kill`, `revise`, or `blocked`. Promotion is a
separate `gate_decision` entry carrying canonical gate ID, result, policy version and hash,
exact package ID, reviewer, evidence fingerprints, blockers, and timestamp. V1 ledger rows
remain readable but cannot prove promotion. Experiment labels belong in tags, never in a
gate ID.

## Data, Execution, and Risk Invariants

- Prices and quantities are lossless decimals; timestamps are UTC nanoseconds.
- Event ordering is event time, provider sequence, receive time, then ingest ID. An event can
  influence a decision only when its receive time is not later than decision time.
- Raw partitions are immutable and committed atomically. Derived artifacts carry raw
  fingerprints, code version, and config hash. DuckDB is a query layer, not source of truth.
- Data quality covers missing intervals, duplicates, ordering, sequences, invalid values,
  crossed or stale books, outliers, timezone/session/roll gaps, and provider truncation.
- Market fills consume opposite-side depth. Limit fills require later trade or book evidence
  and apply partial-fill, queue, and adverse-selection haircuts. Midpoint fills are diagnostic
  only. Bar fills use a later bar and conservative slippage.
- Accounting separates realized and unrealized PnL, cash, collateral, fees, funding, borrow,
  roll, opportunity cost, and rejected or missed fills, with conservation checks after events.
- Risk limits are versioned independently from strategy signals. Fixed-fraction and
  volatility-target sizing are available; Kelly remains an analytical upper bound.

## Adapter Contract

Every adapter exposes discovery, raw fetch, normalization, cross-check, manifest creation,
and cost snapshot operations; settlement snapshot is optional. Capability metadata declares
event types, historical and live-read support, authentication, replay, timestamp quality,
license mode, and maximum promotion mode. Reads use bounded rate limits, heartbeat,
reconnect evidence, archived raw responses, and retries only for idempotent operations.

- Binance is public read-only and begins with BTCUSDT and ETHUSDT. Klines support screening;
  fill-sensitive promotion needs archived trades or books and a second-provider cross-check.
- Futures preserve individual contracts, definitions, sessions, multipliers, tick values, and
  expiry. Public CI uses fixtures. A volume-based continuous series may support signals, but
  execution always references a concrete contract. Without a licensed user archive this lane
  is diagnostic only.
- Polymarket is public read-only and archives discovery, REST books, market WebSocket data,
  timestamped token-specific fees, and resolution metadata. Snapshot/resync, hash or sequence
  checks, complementary-outcome checks, and manual resolution review are required. No order
  endpoint or authenticated user channel is present.

## Paper and Automation Contract

Paper uses the same decision code, canonical events, and config hash as replay. Its worker is
a separate credential-free virtual process and fails closed on stale data, outage, clock skew,
or risk breach. It records decisions, simulated intents, fills, misses, costs, latency,
outages, and risk events. Divergence compares signals, fills, costs, latency, PnL, and
rejections.

Automation is scheduler-neutral. `AutomationSpec` defines owner, trigger, command, inputs,
allowed writes, forbidden actions, timeout, retry policy, alert sink, and freeze procedure.
Every run has an idempotency key and receipt. Retries are limited to idempotent fetch/report
jobs and are forbidden for gate decisions. Required jobs are data health, corpus refresh,
nightly baselines, gate checker, paper observer, risk monitor, drift report, TCA, and weekly
research summary. Reporting is a static read-only bundle; it cannot mutate strategy, limits,
gate, or approval state.

## Test Matrix

- Unit: schemas, chronology, ordering, costs, fills, accounting, policies, ledger migration,
  and exit codes.
- Property and mutation: intervals, hash chain, traversal, duplicates, partial fills,
  conservation, reordered timestamps, changed fingerprints, fake gates, cost mismatch, and
  impossible fills.
- Golden and statistical: exact baseline outputs, hand-checked PSR/DSR/PBO/bootstrap,
  sensitivity, and deterministic clean replay.
- Adapter: recorded public Binance and Polymarket payloads plus a synthetic
  Databento-compatible futures fixture.
- Safety: secret scan, no live order imports, no credentials in paper, and no default CI
  network access.
- End to end: source note through strategy, data, screen, backtest, audit, gate decision,
  paper plan, and blocked or passed paper result. Negative paths retain killed random runs,
  block incomplete data, and prevent optimistic fills from promoting.

## Release Sequence

| Release | Evidence milestone |
| --- | --- |
| v0.1.1 | H0 framework hardening |
| v0.2.0 | R0 research corpus and initial StrategySpecs |
| v0.3.0 | D1 canonical data and three adapter lanes |
| v0.4.0 | B2 deterministic baseline harness |
| v0.5.0 | V3 robustness, risk, and independent audit |
| v0.6.0 | P4 paper runtime, automation, and reporting |
| v1.0.0 | Stable public testing framework after API compatibility review |

## Release Definition of Done

A release milestone is done only when deliverables validate, acceptance checks pass, gate
evidence is machine-readable, ledger evidence is immutable, completion audit links are exact,
there is no open P0/P1 finding, local Python 3.9 and 3.12 matrices pass, and public CI is
green. The release worktree must be committed and clean. Candidate promotion remains
evidence-driven and can never be manufactured from synthetic or backdated paper observations,
but it is not a prerequisite for completing or releasing the testing framework.

Post-implementation release and maintenance work is tracked in
`docs/implementation/REMAINING_WORK_PLAN.md`. That plan does not reopen completed framework
milestones or require a successful strategy.

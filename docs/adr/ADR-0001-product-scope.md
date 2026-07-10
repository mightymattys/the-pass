# ADR-0001: Product Scope

Status: accepted
Date: 2026-07-09
Owner: head_researcher

Command-vocabulary portions are superseded by
[ADR-0009](ADR-0009-consolidated-skill-interface.md). Product scope and the locked live boundary
remain accepted.

## Context

The Pass should be closer to `sous-chef` than to a single trading bot. The first product
must be a reusable plugin and research operating system that can orchestrate strategy
research across asset classes. A narrow crypto-first trading MVP would make the repository
look like a strategy project instead of the framework that judges strategy projects.

## Decision

The MVP is The Pass v0: a public, plugin-first, market-agnostic strategy review station.
The core product is the command workflow, artifact contracts, gates, and evidence ledger.
Specific markets are adapters, not the identity of the system.

Core MVP:

- Codex plugin manifest and skills.
- Slash-command vocabulary: `mise`, `research`, `spec`, `screen`, `backtest`, `taste`,
  `refire`, `simmer`, `paper`, `plate`, and `receipts`.
- Templates for source notes, strategy specs, data manifests, run receipts, metrics reports,
  cost waterfalls, and verdict reports.
- ADR process, public repo policy, safety boundary, and promotion gates.
- Adapter contract for asset classes such as crypto, futures, prediction markets, equities,
  FX, options, rates, credit, and commodities.
- Research and paper/replay only. Live trading remains out of scope unless a separate live
  approval ADR exists.

Out of core MVP:

- Real order placement.
- Broker/exchange credentials.
- Paid market data redistribution.
- Strategy-specific alpha implementation as the public repo's main deliverable.
- Any adapter that cannot produce the required evidence artifacts.

## Alternatives Considered

- Start with one market, such as crypto perps: rejected as product scope because it makes the
  repo look like a strategy bot instead of the judging system.
- Build a generic backtesting engine first: rejected because the durable value is the
  evidence workflow, not another engine.
- Build live automation first: rejected because live order paths require separate risk,
  credential, legal, and operational approval.

## Consequences

- The public repo can be useful before any strategy is implemented.
- Asset-class work is modular and can progress independently.
- The first code should validate contracts and orchestrate workflows, not optimize a single
  trading idea.

## Validation

The MVP is complete only when the plugin can guide a repo through setup, research, spec
creation, run artifact validation, independent review, and receipt generation without any
live order path.

## Review Trigger

Revisit when a real adapter needs functionality that cannot fit the artifact contracts or
when live-capable code is proposed.

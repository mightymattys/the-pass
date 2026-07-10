# ADR-0006: Plugin And Public Distribution

Status: accepted
Date: 2026-07-09
Owner: automation_engineer

The initial skill-list portion is superseded by
[ADR-0009](ADR-0009-consolidated-skill-interface.md). Public distribution and safety decisions
remain accepted.

## Context

The Pass should feel like `sous-chef`: a named workflow product with commands, skills, and
receipts, not a loose collection of trading notes. The repository is intended to be public,
so the first implementation must be safe to publish and useful without private strategy
data.

## Decision

The Pass is plugin-first and public-repo-first.

Public repo contents may include:

- Plugin manifest and skills.
- ADRs, templates, schemas, examples, and documentation.
- Sample artifacts that use synthetic or public-safe data.
- Engine/provider adapter contracts.
- Safety checks that prevent live-capable paths from appearing silently.

Public repo contents must not include:

- Secrets, API keys, private keys, session cookies, or broker credentials.
- Paid data files or data whose license forbids redistribution.
- Private account details, balances, fills, order IDs, or PnL.
- Proprietary strategy parameters that the owner does not intend to publish.

The initial plugin skills are:

- `mise`: prepare a repo for The Pass.
- `research`: convert sources into structured notes and hypotheses.
- `spec`: convert an idea into a StrategySpec.
- `screen`: run or design a fast diagnostic screen.
- `backtest`: run or design a reproducible backtest package.
- `taste`: independently review an experiment package.
- `refire`: fix confirmed findings without expanding scope.
- `simmer`: iterate toward a specific gate or kill condition.
- `paper`: prepare paper/replay observation.
- `plate`: prepare the next-gate approval pack.
- `receipts`: summarize evidence and run ledger.

## Alternatives Considered

- Keep only Markdown docs: rejected because the target is an operational workflow product.
- Build private repo first: rejected because the public artifact contract and safety boundary
  should be designed from the start.
- Publish private strategy outputs: rejected because public distribution should expose the
  system, not confidential edge.

## Consequences

- The first code should support plugin operation and artifact validation.
- Examples must be synthetic or explicitly public-safe.
- GitHub remote should be public once the local repo passes a public-release checklist.

## Validation

The plugin manifest validates, no secret-like content is present, and README/SECURITY
documents explain the public safety boundary.

## Review Trigger

Revisit before publishing marketplace metadata, adding MCP servers/apps, or accepting
external contributions that introduce live trading surfaces.

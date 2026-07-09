# The Pass Working Agreements

This repository is a trading research and automation lab. Treat all future execution
paths as potentially handling real money.

## Hard Rules

- No live trading or real order placement without explicit human approval in an accepted
  ADR.
- No secrets, private keys, API keys, seed phrases, session cookies, or broker credentials
  in the repo.
- Research agents may write research artifacts and code, but must not grant themselves
  live access, leverage, new venues, or larger risk limits.
- Every strategy experiment needs a `StrategySpec`, data manifest, run receipt, cost
  waterfall, metrics report, and verdict.
- Every promotion decision must be gate-based and reproducible.

## Engineering Style

- Simplicity first; no speculative abstractions.
- Prefer small, auditable modules and plain file formats.
- Preserve raw data immutably; normalize into separate derived datasets.
- Separate event time, receive time, decision time, order creation time, ack time, and
  fill time when execution simulation starts.
- Default all backtests to pessimistic fills and costs.

## Research Style

- Classify strategies by edge thesis, not by indicator name.
- Include null/random baselines and intentionally bad baselines.
- Record all tried parameter variants.
- Treat OxfordStrat and similar strategy-review pages as baseline generators, not proof of
  edge.
- Sources cannot influence a promotion gate until they have a structured source note.

## Default Commands

- `python3 -m pip install -e .`
- `python3 scripts/validate_public_repo.py`
- `python3 -m unittest discover -s tests -v`
- `the-pass validate-package examples/synthetic-breakout/package`
- `the-pass validate-package examples/synthetic-random-baseline/package`

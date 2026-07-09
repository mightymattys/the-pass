# The Pass

[![CI](https://github.com/matk0shub/the-pass/actions/workflows/ci.yml/badge.svg)](https://github.com/matk0shub/the-pass/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

**A review station for trading strategy research. Recipes in, evidence out.**

The Pass is a public, plugin-first workflow for turning trading ideas into structured
hypotheses, reproducible evidence packages, independent reviews, and gate-based decisions.
It is inspired by the kitchen split in `sous-chef`: workers can research, implement, and
rerun experiments, but they do not grade their own plate.

The Pass is not a trading bot. It does not place orders. It keeps live trading behind a
separate human approval gate tied to an exact adapter, config hash, venue, and risk
envelope.

## What It Does

- Converts sources and trading ideas into falsifiable `StrategySpec` files.
- Requires data manifests, run receipts, metrics reports, cost waterfalls, and verdicts.
- Reviews experiments for leakage, overfitting, unrealistic execution, and risk gaps.
- Keeps market-specific work behind adapters so crypto, futures, prediction markets,
  equities, FX, options, and other markets can share one evidence workflow.
- Preserves a public-safe boundary: no secrets, no broker credentials, no paid data files,
  no private account details.

## Command Line

The plugin command vocabulary is intentionally small:

| Command | Purpose |
| --- | --- |
| `/the-pass:mise` | Prepare a repo for The Pass. |
| `/the-pass:research` | Turn sources into structured notes and hypotheses. |
| `/the-pass:spec` | Convert an idea into a `StrategySpec`. |
| `/the-pass:screen` | Run or design diagnostic screening. |
| `/the-pass:backtest` | Build a reproducible evidence package. |
| `/the-pass:taste` | Independently review data, stats, execution, and risk. |
| `/the-pass:refire` | Fix confirmed findings without expanding scope. |
| `/the-pass:simmer` | Iterate toward one gate or kill condition. |
| `/the-pass:paper` | Prepare paper/replay observation. |
| `/the-pass:plate` | Package evidence for the next human-controlled gate. |
| `/the-pass:receipts` | Summarize runs, costs, verdicts, and blockers. |

See [docs/plugin/COMMANDS.md](docs/plugin/COMMANDS.md) for the full command contract.

## Project Map

- [Main plan](docs/research/the-pass-plan.md)
- [Implementation build plan](docs/implementation/BUILD_PLAN.md)
- [Completion audit](docs/implementation/COMPLETION_AUDIT.md)
- [Artifact lifecycle](docs/implementation/ARTIFACT_LIFECYCLE.md)
- [Skill contracts](docs/implementation/SKILL_CONTRACTS.md)
- [Validation and safety](docs/implementation/VALIDATION_AND_SAFETY.md)
- [Adapter contract](docs/adapter-contract.md)
- [Adapter examples](examples/adapters/)
- [ADR decisions](docs/adr/)
- [Artifact schemas](schemas/)
- [Artifact templates](templates/)
- [Public-safe golden path example](examples/synthetic-breakout/)
- [Public-safe killed baseline example](examples/synthetic-random-baseline/)
- [Public release checklist](docs/public/RELEASE_CHECKLIST.md)

## Current State

The repository is ready for implementation work:

- Plugin manifest and skills are present.
- Core ADRs are accepted.
- Artifact templates and JSON Schemas exist.
- Public safety validation and CI are configured.
- Synthetic golden path and killed baseline examples exercise the first end-to-end workflow target.
- Adapter descriptors cover a dummy adapter, a concrete public crypto data adapter, and generic
  futures and prediction-market descriptors without core market-specific logic.

Run local validation:

```bash
python3 -m pip install -e .
python3 scripts/validate_public_repo.py
python3 -m unittest discover -s tests
the-pass validate-package examples/synthetic-breakout/package
the-pass validate-package examples/synthetic-random-baseline/package
the-pass validate examples/adapters/crypto-binance-spot-klines.yaml --type adapter
the-pass receipts add examples/synthetic-breakout/package --ledger /tmp/the-pass-ledger.jsonl
the-pass receipts add examples/synthetic-random-baseline/package --ledger /tmp/the-pass-ledger.jsonl
the-pass receipts verify --ledger /tmp/the-pass-ledger.jsonl
```

Codex plugin developers can also run the bundled plugin validator against the repo root.

## Safety Boundary

Public contributions should improve the workflow, schemas, examples, docs, validators, or
adapter contracts. Do not commit secrets, paid market data, broker credentials, private
fills, account balances, real order IDs, or proprietary strategy outputs.

Live-capable code requires a separate accepted ADR, dry-run proof, risk review, credential
boundary, rollback plan, and explicit human approval.

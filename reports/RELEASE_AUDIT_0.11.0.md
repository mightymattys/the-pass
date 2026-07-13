# The Pass v0.11.0 Release Audit

Audit date: 2026-07-13

Framework status: **PASS FOR RELEASE CANDIDATE**

Candidate status: **BLOCKED BY DESIGN**

The framework is usable for trusted local strategy testing. No bundled strategy has enough real
market, paper-window, or independent promotion evidence to pass a candidate gate.

## Scope

Version 0.11.0 adds a supported strategy descriptor and subprocess runtime, immutable provider
ingest, generic deterministic backtests, strategy-driven robustness sweeps, resumable paper
observation, evidence-scoped research reporting, model-catalog freshness enforcement, and
domain-specific automation handlers.

The release does not add an authenticated market channel, credential loader, order transport,
automatic gate approval, internal scheduler, or live capability.

## Findings And Disposition

| Severity | Finding | Disposition |
| --- | --- | --- |
| P0 | Public API exposed `StrategyRunner` but no supported custom-strategy entry point | Resolved by descriptor parsing, bounded worker, `backtest run`, and offline example |
| P0 | Adapters were not connected to immutable ingest | Resolved by `data ingest` and atomic evidence bundles |
| P0 | Paper replay was one-shot and not resumable | Resolved by immutable batches, hash-chain invocations, replay, and prefix verification |
| P1 | Execution and cost assumptions were implicit | Resolved by versioned execution configuration and visible package evidence |
| P1 | Endpoint smoke did not exercise the full public pipeline | Resolved by temporary Binance run and Polymarket scanner packages |
| P1 | Research scope and model-catalog age were not machine checked | Resolved by evidence-scope and catalog freshness commands |
| P1 | Named automation jobs could complete through a generic worker | Resolved by domain handlers that require and fingerprint inspected evidence |
| P1 | Robustness statistics were detached from user strategy execution | Resolved by preregistered strategy sweep execution across every split and variant |

The independent diff review reproduced three additional findings and verified their fixes:

- paper worker failure after batch commit now persists a tracked frozen observation and invocation;
- generic packaging rejects a QualityReport whose event fingerprint or row count differs;
- robustness registration is create-only, fsynced before the first worker, and binds the actual
  strategy source SHA-256 plus parsed execution fingerprint.

The reviewer reran all three reproductions and reported no remaining P0 or P1 in the reviewed
runtime/evidence scope. No known P0 or P1 implementation finding remains open.

## Local Verification

- `uv lock` and `uv sync --extra data --extra research --extra dev`: pass.
- `git diff --check`: pass.
- `uv run ruff check .`: pass.
- `uv run python -m unittest discover -s tests -v`: 215 tests, pass.
- `uv run python scripts/validate_public_repo.py`: pass, including roadmap, corpus, D1, B2,
  V3, P4, plugin, secret, and forbidden live-path checks.
- `uv build` plus `scripts/validate_distribution.py`: wheel and clean installed CLI pass.
- Claude plugin and marketplace strict validation: pass.
- Offline custom strategy ingest, double-run backtest, package validation, and receipt: pass.
- Public read-only diagnostic pipeline: pass for Binance and Polymarket; all outputs remain
  diagnostic and provider payloads are temporary.
- Model catalog current at 2 days; simulated 31-day age blocks with exit `2`.

## Research Evidence Result

The corpus contains 50 structured sources. The evidence-scope report currently classifies 2 as
`full_text`, 5 as `abstract`, 1 as `metadata`, 2 as `operator_material`, 21 as
`reviewed_unspecified`, and 19 as `blocked`. None currently satisfies the stricter explicit-locator
promotion rule, so `promotion_eligible_count` is 0. This is an honest candidate blocker, not a
framework failure.

## Public Diagnostic Result

- Binance: 16 one-minute BTCUSDT bars, deterministic double-run verified, package validated,
  verdict `blocked`.
- Polymarket: one public CLOB book snapshot, timestamped dynamic fee snapshot, spread scanner
  package fingerprinted, promotion disabled.
- Futures: synthetic fixture replay passes; licensed archives remain user-supplied and untracked.

## Publication Gates

- [x] Local implementation, test, safety, distribution, and plugin matrix passes.
- [x] README, usage guide, CLI contract, changelog, plan, and release notes describe v0.11.0.
- [x] Independent final diff review is recorded with no unresolved P0/P1.
- [ ] Pull request passes Python 3.9 and 3.12 required checks and is merged to `main`.
- [ ] Tag `v0.11.0` publishes wheel, sdist, checksums, and this audit.
- [ ] Published release assets are downloaded and clean-install verified.

Until the remaining publication gates pass, this document describes a locally verified release
candidate. It never grants a strategy promotion decision.

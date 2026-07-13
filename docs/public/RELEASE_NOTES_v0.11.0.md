# The Pass v0.11.0

Version 0.11.0 turns the existing evidence framework into a supported user-strategy tester.

## Highlights

- `the-pass backtest run` executes a trusted local strategy in two fresh bounded subprocesses and
  packages only identical results.
- `the-pass data ingest` creates atomic, immutable evidence bundles for Binance, Polymarket, or a
  local futures archive. Public network access requires explicit `--network`.
- `the-pass robustness sweep` executes every preregistered variant/split and retains failures.
- `the-pass paper observe` resumes from immutable event batches, verifies historical output
  prefixes, and freezes on data, risk, config, overlap, or tamper breaches.
- Automation jobs now inspect domain evidence instead of emitting generic success snapshots.
- Research evidence scope and model-catalog age are independently auditable.
- The opt-in public smoke builds a temporary Binance diagnostic run package and Polymarket scanner
  package, then retains metadata fingerprints rather than provider payloads.

## First Run

Follow [`examples/custom-strategy/README.md`](../../examples/custom-strategy/README.md) for a fully
offline ingest-to-package smoke. The example proves runtime behavior only and remains blocked for
promotion.

Run `uv run python scripts/smoke_public_adapters.py --format json` only when public network access
and provider terms have been reviewed. It never authenticates or writes to a venue.

## Safety

The public repository still contains no authenticated order client, credential loader, transaction
signer, or live order transport. Custom strategy files are trusted local code; subprocess isolation
contains failures and strips credentials but is not an OS sandbox.

## Compatibility

Existing baseline, one-shot paper, artifact, ledger, gate, workflow, and plugin interfaces remain
available. New commands are additive. Existing immutable evidence is not rewritten.

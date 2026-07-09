# Validation And Safety

The Pass should fail closed. Missing evidence, ambiguous data, or live-capable paths block
promotion.

## Validation Layers

1. Public repository validation.
2. Plugin manifest validation.
3. Artifact schema validation.
4. Package validation.
5. Gate validation.
6. Public release validation.

## Public Repository Validation

`scripts/validate_public_repo.py` must check:

- Plugin manifest exists and has required metadata.
- All expected skills exist.
- All core schemas exist and are valid JSON.
- No high-confidence secret patterns are present.
- No leftover scaffold placeholders.
- No unexpectedly large tracked-style files.

Future additions:

- Detect live order-placement keywords in core plugin paths.
- Detect common paid data dump extensions under tracked paths.
- Validate artifact schemas with a portable schema linter.
- Run live-boundary static checks before accepting adapter code.

## Artifact Validation

Planned CLI:

```bash
the-pass validate <artifact>
the-pass validate-package <run-dir>
the-pass receipts add <run-dir>
the-pass receipts verify
the-pass receipts
```

Rules:

- YAML and JSON inputs are accepted.
- Every artifact declares or implies its schema.
- Required fields must be present before gate use.
- Validation errors must be actionable and point to fields.

## Package Validation

A run package is valid only if it contains:

- `strategy_spec`
- `data_manifest`
- `run_receipt`
- `metrics_report`
- `cost_waterfall`
- `verdict_report`

The receipt must link to the other artifacts and include safety flags:

- `live_trading_enabled: false`
- `real_order_path_available: false`
- `credentials_available: false`

## Receipt Ledger Validation

The receipt ledger is append-only JSONL. Each entry includes:

- deterministic package ID,
- artifact paths and SHA-256 fingerprints,
- strategy ID,
- run ID,
- gate,
- verdict,
- data manifest reference,
- cost waterfall reference,
- open blockers,
- previous entry hash,
- entry hash.

`the-pass receipts add` refuses to append when the existing ledger hash chain is invalid.
`the-pass receipts verify` recomputes the chain and fails if an entry was edited silently.

## Public Safety Blocks

Block public release if any of these are present:

- API keys, private keys, session cookies, wallet seeds, broker credentials.
- Paid data files or data with unclear redistribution rights.
- Private account IDs, balances, fills, order IDs, or PnL.
- Real order placement paths.
- Proprietary strategy parameters not intended for publication.

## Live-Capable Contribution Blocks

Block live-capable code unless an accepted ADR defines:

- adapter,
- venue,
- credential boundary,
- dry-run proof,
- risk envelope,
- max loss,
- rollback plan,
- incident runbook,
- explicit human approval process.

## CI Requirements

Every pull request should run:

```bash
python3 -m pip install -e .
python3 scripts/validate_public_repo.py
python3 -m unittest discover -s tests
the-pass validate-package examples/synthetic-breakout/package
the-pass validate-package examples/synthetic-random-baseline/package
the-pass validate examples/adapters/dummy-diagnostic.yaml --type adapter
the-pass validate examples/adapters/crypto-binance-spot-klines.yaml --type adapter
the-pass validate examples/adapters/generic-futures-contract.yaml --type adapter
the-pass validate examples/adapters/generic-prediction-market.yaml --type adapter
the-pass receipts add examples/synthetic-breakout/package --ledger /tmp/the-pass-ledger.jsonl
the-pass receipts add examples/synthetic-random-baseline/package --ledger /tmp/the-pass-ledger.jsonl
the-pass receipts verify --ledger /tmp/the-pass-ledger.jsonl
```

Codex plugin developers should also run the bundled plugin validator from their local Codex
skill/tooling install against the repo root.

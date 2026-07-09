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
- All core schemas pass the JSON Schema Draft 2020-12 schema checker.
- Public-safe example packages and adapter descriptors are present.
- Fixture data fingerprints match their manifests.
- No high-confidence secret patterns are present.
- No leftover scaffold placeholders.
- No unexpectedly large tracked-style files.
- No paid/private data dump extensions are tracked.
- `data/raw/` and `data/normalized/` do not contain tracked data files.
- Core code/config paths do not contain known live order-placement API patterns.

## Artifact Validation

Implemented CLI:

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
- Core run artifacts and all slash-workflow outputs have registered JSON Schemas.
- Required fields must be present before gate use.
- Validation errors must be actionable and point to fields.
- Adapter artifacts receive additional contract checks for provider review, mode safety,
  timestamp, cost, fill, risk, and settlement policies.
- Workflow artifacts receive state-dependent checks, such as blocking findings preventing
  `pass` and blocking divergence breaches preventing `risk_review_candidate`.

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

Links must point to the exact canonical artifact, not merely to any existing file. Multiple
files for the same artifact type (for example both JSON and YAML) make the package ambiguous
and invalid.

A `paper_candidate` additionally requires schema-valid independent findings with a passed
`research_gate`, a reviewer distinct from strategy/run ownership, a matching verdict owner,
calculated gross and net evidence, a null/random baseline result, no failed gates, and a
research- or paper-mode adapter. Calculated evidence means finite numeric values, at least one
trade, and explicit order, fill, latency, fee, and slippage assumptions.
The data manifest must also identify provider, license, time coverage, schema, quality policy,
positive row count, and a 64-character SHA-256 fingerprint. Promotion cost waterfalls must
contain numeric fee/spread/slippage components whose sum reconciles gross PnL to net PnL.
Promotion also requires an explicit out-of-sample or walk-forward holdout window, numeric
DSR/PSR or PBO evidence, stress-test results, parameter-stability evidence, and a predefined
train/test plus holdout policy.
Every source note used for promotion must contain the claim, evidence, limitations, market
applicability, required tests, failure modes, and system requirements, and its status must be
`reviewed` or `implemented`.

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

`the-pass receipts add` refuses to append when the existing ledger or any referenced artifact
is invalid. `the-pass receipts verify` recomputes the chain and artifact hashes and fails if
an entry or recorded artifact was edited silently.

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

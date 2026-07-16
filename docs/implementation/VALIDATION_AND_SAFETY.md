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
the-pass gate evaluate <run-dir> --gate <gate> --reviewer <reviewer> \
  --trusted-reviewers <registry-file-or-directory> --output <decision>
the-pass receipts add-decision <decision> --trusted-reviewers <registry-file-or-directory>
the-pass receipts verify --trusted-reviewers <registry-file-or-directory>
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
train/test plus holdout policy. Those values must be derived from a schema-valid
`robustness_report.v2`; validation recomputes its matrix statistics, null comparison, neighboring
parameter stability, mandatory stress coverage, runtime eligibility, and fingerprints.
Every source note used for promotion must contain the claim, evidence, limitations, market
applicability, required tests, failure modes, and system requirements, and its status must be
`reviewed` or `implemented`.

## Receipt Ledger Validation

The receipt ledger is append-only JSONL. V2 entries distinguish immutable runs from gate
decisions. Run entries include:

- deterministic package ID,
- artifact paths and SHA-256 fingerprints,
- strategy ID,
- run ID,
- verdict,
- data manifest reference,
- cost waterfall reference,
- open blockers,
- previous entry hash,
- entry hash.

Gate-decision entries additionally include the canonical gate, computed result, policy
version/hash, independent reviewer, external reviewer-registry fingerprint, exact package ID, and
decision evidence. A package-local key registry proves signature consistency but is not an
authorization source. A run entry alone never proves gate passage. Legacy v1 entries remain
verifiable but cannot prove a v2 gate.

`the-pass receipts add` and `the-pass receipts add-decision` refuse to append when the
existing ledger or any referenced artifact is invalid. `the-pass receipts verify` recomputes
the chain and artifact hashes, rebuilds every v2 run, and replays every v2 gate decision in order
against the bundled policy and the same external trust registry used during evaluation. A gate can
satisfy a prerequisite only after that semantic replay. This fails closed for handwritten
decisions, self-issued reviewer identities, forged hash-consistent entries, stale policies, and
silently edited evidence.

Authoritative v2 replay also enforces the resolved package path, run-before-gate ordering,
globally unique package IDs, and complete successor lineage. Target-gate remediation requires a
recorded exact-package non-pass decision that fingerprints a confirmed finding. Transition,
remediation, and no-progress budget exhaustion are terminal and cannot be reset through resume
flags or caller-supplied counters.

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
the-pass receipts --ledger /tmp/the-pass-ledger.jsonl add examples/synthetic-breakout/package
the-pass receipts --ledger /tmp/the-pass-ledger.jsonl add examples/synthetic-random-baseline/package
the-pass receipts --ledger /tmp/the-pass-ledger.jsonl verify
```

Codex plugin developers should also run the bundled plugin validator from their local Codex
skill/tooling install against the repo root.

The versioned release matrix, including all seven skill validators and installed-wheel checks,
is recorded in `reports/RELEASE_AUDIT_0.8.0.md` rather than duplicated here.

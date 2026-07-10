# Public Release Checklist

Use this before pushing or publishing The Pass.

Status: passed for `main` on 2026-07-09.

## Repository Safety

- [x] No secrets, keys, tokens, cookies, or credentials.
- [x] No paid data files or license-restricted data.
- [x] No private account balances, fills, order IDs, or PnL.
- [x] No live order placement path.
- [x] No proprietary strategy parameters unless intentionally public.

## Plugin Readiness

- [x] `.codex-plugin/plugin.json` validates.
- [x] Every skill has a clear trigger and safety boundary.
- [x] Every skill passes the canonical skill validator and uses its folder name as frontmatter name.
- [x] Skill implementation contracts are documented.
- [x] README explains the product and live-trading boundary.
- [x] ADRs for product scope, storage, engine, providers, risk, and public distribution are
      accepted.

## Artifact Readiness

- [x] Templates and versioned schemas exist for all registered research, core, adapter,
  gate-decision, and slash-workflow artifacts.
- [x] Artifact lifecycle is documented.
- [x] Public examples are synthetic or public-safe.
- [x] Synthetic golden path package is present and stays blocked from paper promotion.
- [x] Killed random baseline package is present.
- [x] Adapter descriptors validate for dummy, crypto, futures, and prediction-market examples.

## Distribution

- [x] LICENSE exists.
- [x] CONTRIBUTING exists.
- [x] SECURITY exists.
- [x] CI validates the public scaffold.
- [x] GitHub repository visibility is public only after this checklist passes.

Evidence:

```bash
python3 scripts/validate_public_repo.py
python3 -m unittest discover -s tests
the-pass validate-package examples/synthetic-breakout/package
the-pass validate-package examples/synthetic-random-baseline/package
the-pass validate examples/adapters/crypto-binance-spot-klines.yaml --type adapter
the-pass receipts add examples/synthetic-breakout/package --ledger /tmp/the-pass-ledger.jsonl
the-pass receipts add examples/synthetic-random-baseline/package --ledger /tmp/the-pass-ledger.jsonl
the-pass receipts verify --ledger /tmp/the-pass-ledger.jsonl
```

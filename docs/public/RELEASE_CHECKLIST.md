# Public Release Checklist

Use this before pushing or publishing The Pass.

Status: `v0.10.0` published and reverified from freshly downloaded release assets on 2026-07-12.

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
- [x] Python 3.9 and 3.12 pass the exact matrix recorded in the release audit.
- [x] Ruff and `uv lock --check` pass.
- [x] Wheel and sdist build without warnings.
- [x] The wheel passes clean installation and CLI validation outside the checkout.
- [x] Branch protection requires both Python CI contexts and pull-request review.
- [x] Release publication is gated by `.github/workflows/release.yml`.
- [x] The repository owner explicitly authorized an administrative review exception for PR #11
      after both required CI contexts passed; no independent GitHub approval was recorded.
- [x] The repository owner explicitly authorized completion of PR #13; it was administratively
      merged only after both required CI contexts and the full local release matrix passed.
- [x] The audited release commit is tagged `v0.10.0` and the release workflow publishes matching
      assets and checksums.

Release evidence:

- `https://github.com/mightymattys/the-pass/pull/11`
- `https://github.com/mightymattys/the-pass/pull/13`
- `https://github.com/mightymattys/the-pass/pull/14`
- `https://github.com/mightymattys/the-pass/pull/15`
- `https://github.com/mightymattys/the-pass/actions/runs/29206594772`
- `https://github.com/mightymattys/the-pass/actions/runs/29206779773`
- `https://github.com/mightymattys/the-pass/releases/tag/v0.10.0`
- `reports/RELEASE_AUDIT_0.10.0.md`
- `reports/POST_RELEASE_AUDIT_0.10.0.md`
- `reports/RELEASE_AUDIT_0.9.1.md`
- `reports/POST_RELEASE_AUDIT_0.9.1.md`
- `docs/public/USAGE_GUIDE.md`
- `reports/CROSS_AGENT_ORCHESTRATION_AUDIT_0.9.0.md`
- `reports/FULL_REPOSITORY_STABILITY_AUDIT_2026-07-10.md`
- `reports/benchmarks/baseline-v0.7.0.json`
- `reports/network/public-adapter-smoke-v0.7.0.json`
- `reports/network/research-links-v0.7.0.json`

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

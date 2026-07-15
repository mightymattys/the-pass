# Contributing

The Pass is public, but trading research can expose private edge, account details, and
regulated activity. Contributions should improve the framework, contracts, documentation,
schemas, tests, or public-safe examples.

## Allowed Contributions

- Plugin skills and workflow improvements.
- Artifact schemas and validators.
- Synthetic or clearly public-safe examples.
- Adapter contracts and provider review templates.
- Documentation, ADRs, safety checks, and test fixtures.

## Do Not Commit

- API keys, private keys, session cookies, broker credentials, seed phrases, or secrets.
- Paid data files or redistributable data with unclear licensing.
- Private account balances, order IDs, fills, PnL, or personal identifiers.
- Live order placement code without an accepted live-boundary ADR.
- Proprietary strategy parameters that are not intended to be public.

## Review Standard

Every meaningful change should preserve:

- No live trading by default.
- Reproducible evidence artifacts.
- Gate-based promotion.
- Public-safe examples.
- Explicit data/provider licensing boundaries.

## Documentation Ownership

- `README.md` owns the one-screen explanation and shortest install-and-run path.
- `docs/public/GETTING_STARTED.md` owns the complete beginner workflow, first prompt, data choices,
  offline smoke, result states, and common setup failures.
- `docs/public/INSTALLATION.md` owns package-manager and clean-install variants.
- `docs/public/USAGE_GUIDE.md` owns advanced gate, supervisor, direct CLI, custom strategy, adapter,
  paper, and delegation operations.

When a command or explanation already has an owner, link to it instead of copying the full block
into another guide. Keep only the minimal README duplication needed for a standalone repository
front page.

# The Pass v0.14.0 Release Audit

Date: 2026-07-16

## Scope

- robustness evidence derivation and package binding;
- reviewer authorization trust anchor;
- hardened runtime launcher authorization and active probes;
- deterministic candidate assembly and review-stage write boundaries;
- public CLI, plugin, schema, template, documentation, and distribution compatibility.

## Required Verification

```bash
uv lock --check
uv run ruff check .
uv run python scripts/validate_public_repo.py
uv run python -m unittest discover -s tests -v
uv build
uv run python scripts/validate_distribution.py dist/the_pass-*.whl
```

## Result

- Unit tests: 242 passed.
- Ruff: passed.
- Public repository validation: passed.
- Release build: passed for sdist and `the_pass-0.14.0-py3-none-any.whl`.
- Clean installed-wheel validation: passed, including packaged schemas, policies, and CLI.
- Offline custom-strategy ingest, backtest package validation, and clean reproduction: passed.
- Claude plugin and marketplace strict validation: passed.

## Security Conclusions

- Package-local reviewer keys are not authorization roots.
- All post-gate ledger mutation and successor paths replay against the same explicit trust root.
- Self-declared sandbox enforcement is not promotional evidence.
- Promotion statistics are recomputed from exact stored observations.
- Candidate core artifacts are generated through one validated successor operation.
- Live trading remains locked and no order transport or credential loader was added.

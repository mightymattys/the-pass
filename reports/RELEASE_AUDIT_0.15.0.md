# The Pass v0.15.0 Release Audit

Date: 2026-07-16

## Scope

- train-select-test walk-forward correctness and robustness-report v3 validation;
- latency, participation, impact, dynamic fees, futures multiplier, funding, and settlement;
- canonical JSONL worker transport and deterministic streaming replay;
- strategy/simulator checkpoints and incremental paper/full-replay parity;
- public schemas, fixtures, plugins, documentation, distribution, and live-boundary safety.

## Required Verification

```bash
uv lock --check
uv run ruff check .
uv run python scripts/validate_public_repo.py
uv run python -m unittest discover -s tests -v
uv run python scripts/benchmark_framework.py
claude plugin validate .claude-plugin/plugin.json --strict
claude plugin validate . --strict
DIST_DIR="$(mktemp -d)"
uv build --out-dir "$DIST_DIR"
uv run python scripts/validate_distribution.py "$DIST_DIR"/the_pass-*.whl
```

## Result

- Python 3.12 unit and integration suite: 249 passed.
- Isolated Python 3.9 unit and integration suite: 249 passed.
- GitHub PR #26 CI: Python 3.12 passed in 1m44s and Python 3.9 passed in 1m53s.
- Ruff, compileall, lockfile check, and `git diff --check`: passed.
- Public repository validation: passed through H0, R0, D1, B2, V3, P4, and locked L5-L6.
- B2 clean replay: 6 packages and 11 variants reproduced deterministically.
- V3 public audit: 6 folds, 48 complete train/test cells, 192 OOS observations, no failed cells;
  synthetic candidate correctly blocked.
- Claude plugin and marketplace strict validation: passed.
- Build: passed for sdist and `the_pass-0.15.0-py3-none-any.whl`.
- Clean installed-wheel validation: passed, including packaged v3 schema, policies, and CLI.
- Release-candidate SHA-256: wheel
  `ab833c37810832859bc668fbd5c1cb806697e479baf791bfcd80b13a37ba5f52`; sdist
  `d77868fff84f67fbaf5fc63c13b831a302bd77b1d26c6e5c8320d592a7a45264`.
- 10,000-event benchmark: deterministic replay passed, peak Python memory 53,932,099 bytes,
  replay 1.89 seconds on the audited macOS ARM host.

## Safety Conclusions

- Test-fold evidence cannot influence fold selection.
- Promotion statistics are recomputed from aligned untouched OOS periodic returns.
- Fills require post-decision latency evidence and explicit liquidity/cost constraints.
- Derivative lifecycle cashflows are explicit and portfolio conservation is checked.
- Incremental paper state is fingerprinted and periodically checked against clean replay.
- Historical compatibility remains readable but cannot bypass current promotion requirements.
- Live trading remains locked and no order transport or credential loader was added.

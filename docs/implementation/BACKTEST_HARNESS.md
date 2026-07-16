# Screen And Backtest Harness

The reference B2 harness is deliberately small and engine-neutral. Strategies emit
`SimulatedIntent` objects from canonical events. Fill, cost, portfolio, and risk policies
are injected protocols. The same decision contract can therefore be replayed by the paper
runtime without changing strategy logic.

## User Strategy Runtime

`the-pass backtest run` loads one strategy file from an explicit workspace root. The descriptor,
source, config, execution assumptions, risk mode, and canonical events are hashed. Two fresh
subprocess runs must match exactly before package creation.

The default `trusted_local` mode strips credential environment variables, blocks known
network/order imports, and enforces a process timeout/output limit. It explicitly records
`network_enforcement: none` and `filesystem_enforcement: none`; this is failure containment for
trusted code, not an OS sandbox. The optional `hardened` mode requires an operator-supplied
executable sandbox launcher plus a trust policy allowlisting its exact hash and requirements. The
launcher must enforce the declared OS boundary and write an exact attestation tied to its own hash
and request fingerprint. Before each worker, an active probe attempts forbidden reads/writes,
loopback access, and execution without OS CPU/file-size limits. No launcher is bundled, and missing,
mismatched, or failed evidence blocks promotion.

The generic package copies and cross-validates the supplied StrategySpec, DataManifest, and
QualityReport. It never replaces them with synthetic claims. A generic run always starts with a
`blocked` verdict and still requires robustness, risk, and independent review.

`robustness_report.v2` is authoritative promotion evidence. It stores the registered variants,
source-package binding, event/descriptor/execution fingerprints, complete fold matrix, failed cells,
purge/embargo policy, null baseline, mandatory stresses, and parameter stability. Validation
recomputes PBO, PSR, DSR, and Reality Check/SPA. Summary values in `metrics_report` must exactly
match this report.

After independent findings, `the-pass candidate assemble` creates the successor package and derives
the metrics/verdict references. Agents and users should never hand-edit a recorded run into
`paper_candidate`.

## Fill Evidence

- Market intents consume opposing book depth and record unfilled remainder.
- Limit intents require a later trade or book event; queue and adverse-selection haircuts
  are explicit.
- Bar intents fill only at a later bar open with adverse slippage.
- Midpoint fills are diagnostic and have `promotion_eligible = false`.
- Every fill is bound to the intent instrument and rejects invalid price, size, fee, or cost values.

## Metrics And Costs

- Net metrics use the accounting equity curve after explicit costs.
- Gross path metrics use a separate reconstructed equity curve that adds timestamped fill costs
  back at each observation; unallocated costs fail the reconstruction instead of silently reusing
  net returns.
- Annualization is explicit in `metrics_report.annualization`. Continuous crypto and prediction
  markets use a 365.25-day calendar; listed-futures diagnostics use 252 sessions of 6.5 hours.
  Both derive observations per year from the median equity interval.
- A `paper_candidate` without a positive, named annualization policy is invalid.

## Reproduction

```bash
uv run --extra data --extra research python scripts/run_b2_baselines.py --clean
uv run --extra data --extra research python scripts/validate_b2_harness.py
```

The generated packages are under `examples/b2-baselines/`. Search spaces are written
before simulation. A non-empty output directory or changed preregistration is rejected.
The executable custom path is documented under `examples/custom-strategy/`.

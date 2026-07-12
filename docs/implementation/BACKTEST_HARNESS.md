# Screen And Backtest Harness

The reference B2 harness is deliberately small and engine-neutral. Strategies emit
`SimulatedIntent` objects from canonical events. Fill, cost, portfolio, and risk policies
are injected protocols. The same decision contract can therefore be replayed by the paper
runtime without changing strategy logic.

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

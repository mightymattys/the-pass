# Canonical Data Foundation

The D1 data layer is provider-neutral and read-only at every external boundary.

## Contracts

- `Instrument` records tick size, lot size, multiplier, expiry, and contract type with
  lossless decimal values.
- `CanonicalEvent` separates provider event time from local receive time in UTC
  nanoseconds and sorts by event time, provider sequence, receive time, and ingest ID.
- Canonically ordered replay evidence must also have nondecreasing receive time. The
  quality report blocks receive-time inversions before the simulator enforces the same
  invariant.
- `QualityReport` records every required check even when the count is zero. Errors and
  critical findings quarantine the dataset and block promotion.
- `FeatureManifest` recomputes and verifies the canonical input-event fingerprint before
  binding derived rows to that dataset, code version, and configuration hash.

Raw canonical events are written to immutable Parquet partitions under
`source/venue/instrument/date`. Writes use a sibling staging directory and an atomic
rename; an existing partition is never replaced. DuckDB is a query layer only and is
not a source of truth.

## Adapter Boundaries

- Binance uses the public market-data-only REST and WebSocket hosts. Historical klines
  and aggregate trades paginate within each half-open request window. Kline events retain
  local receive time, keep provider close time in their payload, and exclude bars that
  were not closed when received. Bar dataset plans require `expected_interval_ns`.
  Klines remain diagnostic for fills; promotion requires archived trades or books.
- Futures reads a local Databento-compatible archive. The repository contains only a
  synthetic fixture and remains diagnostic-only without a user-supplied licensed
  archive. Volume rolls require two consecutive challenger volume wins by default and
  back-adjust old/new closes observed at the same roll timestamp.
- Polymarket uses public Gamma discovery, CLOB books, dynamic token-specific fee rates,
  and the unauthenticated market channel. No user channel or transaction transport is
  implemented. Provider timestamps outside 2020-01-01 through receive time plus one day
  are rejected as likely unit errors.

The public network smoke is opt-in:

```bash
python3 scripts/smoke_public_adapters.py --format json
```

Default tests are fully offline and use recorded or synthetic fixtures.

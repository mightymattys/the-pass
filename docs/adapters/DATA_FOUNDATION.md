# Canonical Data Foundation

The D1 data layer is provider-neutral and read-only at every external boundary.

## Contracts

- `Instrument` records tick size, lot size, multiplier, expiry, and contract type with
  lossless decimal values.
- `CanonicalEvent` separates provider event time from local receive time in UTC
  nanoseconds and sorts by event time, provider sequence, receive time, and ingest ID.
- `QualityReport` records every required check even when the count is zero. Errors and
  critical findings quarantine the dataset and block promotion.
- `FeatureManifest` binds derived rows to the input fingerprint, code version, and
  configuration hash.

Raw canonical events are written to immutable Parquet partitions under
`source/venue/instrument/date`. Writes use a sibling staging directory and an atomic
rename; an existing partition is never replaced. DuckDB is a query layer only and is
not a source of truth.

## Adapter Boundaries

- Binance uses the public market-data-only REST and WebSocket hosts. Klines are
  diagnostic for fills; promotion requires archived trades or books.
- Futures reads a local Databento-compatible archive. The repository contains only a
  synthetic fixture and remains diagnostic-only without a user-supplied licensed
  archive.
- Polymarket uses public Gamma discovery, CLOB books, dynamic token-specific fee rates,
  and the unauthenticated market channel. No user channel or transaction transport is
  implemented.

The public network smoke is opt-in:

```bash
python3 scripts/smoke_public_adapters.py --format json
```

Default tests are fully offline and use recorded or synthetic fixtures.

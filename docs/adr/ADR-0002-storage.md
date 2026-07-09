# ADR-0002: Storage

Status: accepted
Date: 2026-07-09
Owner: data_steward

## Context

The lab needs immutable raw data, reproducible normalized datasets, and a lightweight
ledger for experiments. The first version should avoid database complexity until multiple
writers or users require it.

## Decision

Use partitioned Parquet files for raw and normalized market data, DuckDB for local
analytical queries, and SQLite for small ledgers in the MVP.

Default paths:

- `data/raw/<source>/<venue>/<instrument>/<date>/`
- `data/normalized/<venue>/<instrument>/<timeframe>/<date>/`
- `experiments/runs/`
- `reports/generated/`

Every dataset must have a manifest with source, licensing note, schema, time range,
fingerprint, and known gaps.

Implementation note (2026-07-09): the MVP receipt ledger shipped as append-only JSONL with
a SHA-256 hash chain in `src/the_pass/ledger.py`. SQLite is deferred until scale or
concurrent-writer requirements justify it.

## Alternatives Considered

- Postgres first: rejected until concurrent writes or multi-user access become real.
- One SQLite database for all data: rejected because tick/depth data will become large.
- CSV-only storage: rejected because schema and type drift are too easy.

## Consequences

- Local-first workflow stays simple.
- Large data files are ignored by git.
- Dataset manifests become mandatory evidence.

## Validation

First ingestion prototype must write a raw sample, normalized sample, and manifest that can
be queried through DuckDB.

## Review Trigger

Revisit when multiple writers need concurrent writes, when data size makes local files
unmanageable, or when remote execution requires shared storage.

# Installation and Clean-Package Quickstart

The Pass supports Python 3.9 and 3.12.

## Install

From a checked-out release:

```bash
python -m pip install ".[data,research,paper]"
the-pass --version
```

From a downloaded wheel:

```bash
python -m pip install "the_pass-0.7.1-py3-none-any.whl[data,research,paper]"
the-pass --version
```

The base package contains JSON Schema validation and ledger support. The `data` extra adds
Parquet, DuckDB, HTTP, and WebSocket dependencies. The `research` extra adds NumPy, pandas,
and SciPy. The `paper` extra is intentionally dependency-light and does not add a live client.

## Validate Evidence

```bash
the-pass validate strategy_spec.yaml --format json
the-pass validate-package path/to/package --format json
the-pass receipts add path/to/package --ledger receipts.jsonl
the-pass receipts verify --ledger receipts.jsonl
```

Packaged schemas and policies are loaded from the installed wheel. A source checkout is not
required. No command needs or loads venue credentials.

## Safety Check

The public package cannot place real orders. `live_gate` exits with code `3`. Candidate paper
and risk evaluation can return code `2` without indicating a software error.

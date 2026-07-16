# Installation and Clean-Package Quickstart

The Pass supports Python 3.9 and 3.12.

Installation requires no exchange credentials, historical dataset, or previous backtest. A real
strategy run eventually needs market history; see [Getting Started](GETTING_STARTED.md) for the
public-data, user-archive, custom-code, and external-backtest paths.

## Install

From a checked-out release:

```bash
python -m pip install ".[data,research,paper]"
the-pass --version
```

As a user-level tool from the published wheel:

```bash
uv tool install \
  "the-pass[data,research,paper] @ https://github.com/mightymattys/the-pass/releases/download/v0.14.0/the_pass-0.14.0-py3-none-any.whl"
uv tool update-shell
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

Guided Codex and Claude Code plugin installation is maintained in
[Getting Started: Install](GETTING_STARTED.md#4-install). For local Claude Code plugin development,
load the checkout directly:

```bash
claude --plugin-dir /path/to/the-pass
```

The Python `workflow` group exposes the same validated state primitives for automation; it does
not bypass independent gate evaluation. Cross-provider delegation is opt-in through
`the-pass agents inspect` followed by `the-pass agents dispatch --execute`; see
[Cross-Runtime Orchestration](../plugin/CROSS_RUNTIME.md).

The simplest setup, data explanation, first prompt, and common failure modes are documented in
[GETTING_STARTED.md](GETTING_STARTED.md). Direct CLI workflows and advanced operation are in
[USAGE_GUIDE.md](USAGE_GUIDE.md).

Packaged schemas and policies are loaded from the installed wheel. A source checkout is not
required. No command needs or loads venue credentials.

## Safety Check

The public package cannot place real orders. `live_gate` exits with code `3`. Candidate paper
and risk evaluation can return code `2` without indicating a software error.

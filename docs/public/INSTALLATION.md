# Installation and Clean-Package Quickstart

The Pass supports Python 3.9 and 3.12.

## Install

From a checked-out release:

```bash
python -m pip install ".[data,research,paper]"
the-pass --version
```

As a user-level tool from the published wheel:

```bash
uv tool install \
  "the-pass[data,research,paper] @ https://github.com/mightymattys/the-pass/releases/download/v0.10.0/the_pass-0.10.0-py3-none-any.whl"
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

For a guided end-to-end research line, install either bundled plugin and use
`/the-pass:run`. Both runtimes consume the same seven skills. A local Claude Code checkout can be
loaded directly:

```bash
claude --plugin-dir /path/to/the-pass
```

The published pinned Claude marketplace supports:

```text
/plugin marketplace add mightymattys/the-pass
/plugin install the-pass@the-pass-tools
```

Codex installation uses the repository's Codex marketplace catalog:

```bash
codex plugin marketplace add mightymattys/the-pass --ref v0.10.0
codex plugin add the-pass@the-pass-tools
```

The Python `workflow` group exposes the same validated state primitives for automation; it does
not bypass independent gate evaluation. Cross-provider delegation is opt-in through
`the-pass agents inspect` followed by `the-pass agents dispatch --execute`; see
[Cross-Runtime Orchestration](../plugin/CROSS_RUNTIME.md).

The complete setup, smoke test, first guided run, direct CLI workflow, and common failure modes are
documented in [USAGE_GUIDE.md](USAGE_GUIDE.md).

Packaged schemas and policies are loaded from the installed wheel. A source checkout is not
required. No command needs or loads venue credentials.

## Safety Check

The public package cannot place real orders. `live_gate` exits with code `3`. Candidate paper
and risk evaluation can return code `2` without indicating a software error.

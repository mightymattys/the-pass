# The Pass Usage Guide

This guide covers the supported way to install The Pass, run the Codex or Claude Code plugin,
test a strategy, inspect evidence, delegate bounded agent work, and continue into paper
observation. The public project never places real orders.

## 1. Understand The Three Layers

The Pass has three cooperating surfaces:

1. The seven slash skills are the guided operator interface. Start with `/the-pass:run`.
2. The `the-pass` Python CLI is the machine authority for validation, workflow state, receipts,
   gates, reference tests, paper simulation, and reports.
3. The working repository is the evidence store. It contains source notes, StrategySpecs,
   immutable run packages, ledgers, findings, and generated reports.

Installing only the plugin is not enough for a complete run: the CLI must also be available to
the agent, and strategy evidence must live in a writable project checkout. The recommended setup
is a fork or clone of this repository plus a user-level CLI installation.

## 2. Install The CLI

Install the released CLI and all non-live research extras with `uv`:

```bash
uv tool install \
  "the-pass[data,research,paper] @ https://github.com/mightymattys/the-pass/releases/download/v0.9.1/the_pass-0.9.1-py3-none-any.whl"
uv tool update-shell
the-pass --version
```

Open a new shell if `the-pass` is not immediately on `PATH`. The expected version is `0.9.1`.
The base package is sufficient for artifact and ledger validation; the command above also installs
Parquet, DuckDB, HTTP/WebSocket, NumPy, pandas, and SciPy support. It does not install a live
trading client.

For repository development instead:

```bash
git clone https://github.com/mightymattys/the-pass.git
cd the-pass
git checkout v0.9.1
uv sync --locked --extra data --extra research --extra dev
uv run the-pass --version
```

## 3. Install A Plugin

### Codex

```bash
codex plugin marketplace add mightymattys/the-pass --ref v0.9.1
codex plugin add the-pass@the-pass-tools
codex plugin list
```

Start a new Codex task after installation so the seven `/the-pass:*` skills are loaded.

For local development against the current checkout, replace the first command with:

```bash
codex plugin marketplace add "$PWD"
codex plugin add the-pass@the-pass-tools
```

### Claude Code

Inside Claude Code:

```text
/plugin marketplace add mightymattys/the-pass
/plugin install the-pass@the-pass-tools
/reload-plugins
```

For local plugin development:

```bash
claude --plugin-dir /absolute/path/to/the-pass
```

Both runtimes expose `run`, `research`, `test`, `review`, `paper`, `plate`, and `status` under the
`/the-pass:*` namespace. Claude also exposes the finite coordinator, researcher, implementer, and
reviewer native agents.

## 4. Verify The Installation

Run these checks before the first strategy:

```bash
the-pass --version
the-pass agents doctor --provider all --format json
```

`agents doctor` checks executable versions and the model-routing catalog. It does not contact a
model or prove provider authentication. A missing Codex or Claude binary matters only when that
provider is selected for cross-provider delegation.

In a source checkout, the complete offline repository check is:

```bash
uv lock --check
uv run ruff check .
uv run python scripts/validate_public_repo.py
uv run python -m unittest discover -s tests -v
```

## 5. Run The Safe Five-Minute Smoke

From a The Pass checkout:

```bash
WORK="$(mktemp -d)"
LEDGER="$WORK/receipts.jsonl"

the-pass validate-package examples/synthetic-breakout/package --format json
the-pass receipts --ledger "$LEDGER" --format json add \
  examples/synthetic-breakout/package
the-pass receipts --ledger "$LEDGER" --format json verify

the-pass backtest baseline --name seeded_random \
  --output "$WORK/random-package" --format json
the-pass validate-package "$WORK/random-package" --format json
```

Expected result:

- the synthetic breakout package validates but does not prove a real edge;
- the ledger appends and verifies one immutable run;
- the seeded random baseline builds a valid package whose verdict is `kill`;
- no network, credentials, paper broker, gate approval, or live operation is used.

## 6. Start A Real Guided Run

Use `/the-pass:run` as the normal front door. A useful first prompt is:

```text
/the-pass:run Research and test a BTCUSDT 15-minute time-series momentum idea to
research_gate. Strategy owner: matty. Run owner: codex-implementer. Independent reviewer:
claude-reviewer. Use public read-only data, conservative costs, a seeded random baseline,
chronological holdout, and stop if fill-sensitive evidence is unavailable.
```

The target must be one of:

- `research_gate`: research, data, screen, backtest, robustness, and independent review;
- `paper_gate`: the previous stages plus a real elapsed paper observation window;
- `risk_review`: the previous stages plus risk evidence and a pending human-decision pack.

`live_gate` is not a valid run target. A new idea should normally target `research_gate` first.

The run creates durable state under `.the-pass/runs/<run-id>/state.yaml`. It advances every stage
that has sufficient evidence and stops honestly at `complete`, `waiting`, `blocked`, or `killed`.
It may stop before the target when data, a license, an independent reviewer, supported execution
evidence, or a paper window is missing. That stop is a valid testing result.

### Supervise The Run To A Terminal Checkpoint

The `0.10.0` source tree can mechanically continue one stage at a time. First inspect without a
model call:

```bash
the-pass agents route --stage research --format json
the-pass workflow execute \
  --state .the-pass/runs/<run-id>/state.yaml \
  --author-provider codex \
  --format json \
  --driver auto
```

Then add `--execute` before `--driver auto`. The option `--driver` must remain last:

```bash
the-pass workflow execute \
  --state .the-pass/runs/<run-id>/state.yaml \
  --author-provider codex \
  --timeout-seconds 1800 \
  --execute \
  --format json \
  --driver auto
```

This uses the locally authenticated Codex and Claude CLIs and may incur provider cost. Each model
receives one stage, not the whole authority chain. The supervisor rejects an unchanged state,
invalid transition, timeout, exhausted cycle budget, or completion without the exact passed gate.
It stops normally with exit `2` for valid `blocked`, `waiting`, or `killed` research outcomes.
`agents doctor` proves only that a binary exists. Authenticate both CLIs before a two-provider run,
or constrain routing with one or more `--available-provider` options. A provider authentication or
model-access failure is not automatically retried through another provider.

The current catalog is limited to GPT-5.6 Luna/Terra/Sol and Claude Sonnet 5/Opus 4.8/Fable 5.
The framework intentionally does not fall back to an older model family.

For independent review, `--author-provider` identifies the provider that produced the candidate.
The route fails closed if no different provider is available. A custom trusted executable may be
placed after `--driver` instead of `auto`; it receives documented `THE_PASS_WORKFLOW_*` and
`THE_PASS_ROUTE_*` environment variables and must advance exactly one stage per invocation.
The supervisor report is written beside the workflow state. Auto mode does not forward venue keys
or direct API-key environment variables to provider processes; it uses the CLIs' local authenticated
configuration.

## 7. Use Focused Skills When Needed

| Command | Use it for |
| --- | --- |
| `/the-pass:research` | Review sources, formalize a falsifiable hypothesis, or create a StrategySpec |
| `/the-pass:test` | Run data checks, a preregistered screen, or a reproducible backtest package |
| `/the-pass:review` | Independently audit one exact package for a named non-live gate |
| `/the-pass:paper` | Prepare or resume isolated paper observation after a research pass |
| `/the-pass:plate` | Build risk evidence and a pending approval input pack after a paper pass |
| `/the-pass:status` | Verify state, ledger, blockers, incidents, and the next legal action |

Use focused commands to resume or inspect a specific station. Do not manually chain them when
`/the-pass:run` can own the workflow state.

## 8. Use The CLI Directly

The CLI is appropriate for scripts, CI, external engines, and deterministic reruns.

Start and inspect workflow state:

```bash
the-pass workflow start \
  --state .the-pass/runs/momentum-001/state.yaml \
  --run-id momentum-001 \
  --strategy-id btc-momentum-v1 \
  --objective "Test BTCUSDT 15m time-series momentum" \
  --target-gate research_gate \
  --strategy-owner matty \
  --run-owner implementer-a \
  --ledger .the-pass/receipts.jsonl \
  --format json

the-pass workflow status \
  --state .the-pass/runs/momentum-001/state.yaml \
  --format json
```

At every finalized package boundary:

```bash
the-pass validate-package experiments/runs/<strategy>/<run>/package --format json
the-pass receipts --ledger .the-pass/receipts.jsonl --format json add \
  experiments/runs/<strategy>/<run>/package
the-pass receipts --ledger .the-pass/receipts.jsonl --format json verify
```

Only an independent review should evaluate a gate:

```bash
the-pass gate evaluate experiments/runs/<strategy>/<run>/package \
  --gate research_gate \
  --reviewer independent-reviewer \
  --ledger .the-pass/receipts.jsonl \
  --output experiments/runs/<strategy>/<run>/package/gate_decision.research_gate.yaml \
  --format json

the-pass receipts --ledger .the-pass/receipts.jsonl --format json add-decision \
  experiments/runs/<strategy>/<run>/package/gate_decision.research_gate.yaml
```

A run receipt proves that a run happened. It never proves that a gate passed. A gate pass requires
the separate decision for the exact package ID, package path, reviewer, policy hash, and evidence
fingerprints.

## 9. Bring Your Own Strategy Engine

The reference engine supports the bundled baselines and an auditable event simulation. An external
engine may be used when it preserves The Pass contracts.

It must export a package containing at least:

- immutable StrategySpec copy;
- data manifest and unblocked quality evidence;
- run receipt with code/config/data fingerprints;
- complete gross and net metrics;
- cost waterfall reconciled to net PnL;
- verdict report and execution assumptions;
- robustness, risk, and independent audit evidence required by the target gate.

Validate the exported package and append it through the same CLI. External engine output never
bypasses chronology, cost, reviewer, ledger, or gate checks.

## 10. Use Data Adapters Correctly

- Binance Spot and Polymarket support public read-only market data.
- Futures use the Databento-compatible interface and fixture replay. Promotion requires a
  user-supplied licensed archive.
- Klines are suitable for diagnostics; fill-sensitive promotion requires trade or book evidence.
- Polymarket fees are dynamic and token-specific; never use one global flat fee.
- Paid data, provider credentials, authenticated user channels, and raw private outputs do not
  belong in the repository or evidence artifacts.

## 11. Delegate To The Other Provider

Cross-provider delegation is optional and explicit. Begin from `templates/agent_task.yaml`, then:

```bash
the-pass agents inspect path/to/agent-task.yaml --format json
the-pass agents dispatch path/to/agent-task.yaml \
  --output-dir reports/agents --execute --format json
```

Inspect always comes first. It shows the selected provider, `economy|balanced|deep` profile, model,
effort, capabilities, limits, paths, and sanitized invocation without making a paid call.

- Researcher and reviewer tasks are read-only.
- Implementer tasks run in a disposable worktree and return an unapplied patch.
- The caller must review, apply, test, and record an accepted patch.
- A delegated agent cannot delegate again, retry itself, change a gate, write a ledger, approve
  live trading, commit, or push.

## 12. Understand Results And Exit Codes

| Exit | Meaning |
| --- | --- |
| `0` | operation succeeded or the evaluated gate passed |
| `1` | invalid input, schema failure, missing evidence, or technical failure |
| `2` | valid `blocked`, `revise`, `kill`, `waiting`, or `frozen` research result |
| `3` | forbidden safety operation, including the public live boundary |

Exit `2` means The Pass worked and declined progression. Automation must not treat it as a crash or
rewrite the evidence to force exit `0`.

## 13. Resume Without Rewriting History

- Use `/the-pass:status` or `the-pass workflow status` first.
- Resolve the named blocker or wait condition.
- Resume through a validated workflow transition; do not edit state counters by hand.
- Never modify a package after its run receipt is recorded.
- Create a successor package with `the-pass workflow supersede` for new robustness, paper, risk,
  or remediation evidence.
- Every successor receives a new run ID and package ID and must replay prerequisite gates.

## 14. Build Reports

```bash
the-pass report build --repo-root . --output-dir reports/generated/report --format json
the-pass dashboard build --repo-root . --output-dir reports/generated/dashboard --format json
```

The output is static and read-only. It can summarize evidence but cannot modify StrategySpecs,
limits, gate decisions, ledgers, or approval state.

## 15. Common Mistakes

- Installing the plugin but not the `the-pass` CLI.
- Starting with `paper_gate` before an exact research-gated package exists.
- Using the same identity for strategy owner, run owner, and reviewer.
- Editing a recorded package instead of creating a successor.
- Treating a receipt, verdict string, filename, or dashboard label as gate passage.
- Treating exit `2` as a software failure.
- Expecting synthetic examples, klines, or mid-price fills to support promotion.
- Asking an agent to apply its own patch or approve its own result.
- Supplying exchange credentials or asking the public core to place an order.

For exact command arguments, run `the-pass <group> <command> --help`. The stable machine response
and exit-code contract is documented in [CLI_CONTRACT.md](CLI_CONTRACT.md), and slash-skill
semantics are documented in [../plugin/COMMANDS.md](../plugin/COMMANDS.md).

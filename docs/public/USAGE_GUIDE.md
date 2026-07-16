# The Pass Usage Guide

This guide covers the supported way to install The Pass, run the Codex or Claude Code plugin,
test a strategy, inspect evidence, delegate bounded agent work, and continue into paper
observation. The public project never places real orders.

For the shortest setup and first-run path, read [Getting Started](GETTING_STARTED.md). This guide
is the detailed reference for users who need direct CLI control, custom strategies, external
engines, paper observation, or cross-provider delegation.

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

Data requirements and the four supported starting points are defined once in
[Getting Started: Where the Data Comes From](GETTING_STARTED.md#2-where-the-data-comes-from).

## 2. Prerequisites

Complete the installation and offline smoke in [Getting Started](GETTING_STARTED.md#4-install).
Package-manager variants and clean-wheel details live in [Installation](INSTALLATION.md). This
guide does not duplicate those commands.

For source development, run the repository checks documented in [Development](../../README.md#development)
before changing runtime contracts.

## 3. Run Targets and Supervision

Use `/the-pass:run` as the normal front door. The canonical first prompt and its data semantics
live in [Getting Started: Start Your First Real Strategy](GETTING_STARTED.md#6-start-your-first-real-strategy).
This section documents what happens after that prompt creates durable state.

The target must be one of:

- `research_gate`: research, data, screen, backtest, robustness, and independent review;
- `paper_gate`: the previous stages plus a real elapsed paper observation window;
- `risk_review`: the previous stages plus risk evidence and a pending human-decision pack.

`live_gate` is not a valid run target. A new idea should normally target `research_gate` first.

The run creates durable state under `.the-pass/runs/<run-id>/state.yaml`. It advances every stage
that has sufficient evidence and stops honestly at `complete`, `waiting`, `blocked`, or `killed`.
It may stop before the target when data, a license, an independent reviewer, supported execution
evidence, or a paper window is missing. That stop is a valid testing result.

Calling `/the-pass:run` without a new objective may resume an existing non-terminal run. When the
previous strategy is terminal, use a new hypothesis and explicitly say `Start a NEW research run`.

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
The supervisor report is written beside the workflow state. Auto mode does not forward venue keys,
direct API-key environment variables, or reviewer signing keys to provider processes; it uses the
CLIs' local authenticated configuration. Automated stages run in a detached worktree and the parent
applies only the validated evidence patch. A custom driver is trusted and runs directly against the
caller workspace.

An automated independent review does not sign its own result. It stops at `waiting` with completed
review evidence. A designated reviewer must then create the Ed25519 attestation described below.
After signing, resume the workflow from that checkpoint so the deterministic gate stage can verify
the public evidence and continue.

## 4. Use Focused Skills When Needed

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

## 5. Use The CLI Directly

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

Only an independent review should evaluate a gate. Generate each reviewer key once, distribute the
public registry through a reviewed channel, and keep the private key outside the repository. The
command writes a raw Ed25519 private key with mode `0600` and a non-secret public registry:

```bash
the-pass gate keygen \
  --registry-id trading-reviewers-v1 \
  --reviewer independent-reviewer \
  --principal-type human \
  --provider human \
  --created-at 2026-07-15T00:00:00Z \
  --valid-from 2026-07-15T00:00:00Z \
  --valid-until 2027-07-15T00:00:00Z \
  --private-key-output "$HOME/.config/the-pass/independent-reviewer.key" \
  --registry-output reviewer-keys.json \
  --format json

export THE_PASS_REVIEW_SIGNING_KEY="$(cat "$HOME/.config/the-pass/independent-reviewer.key")"

the-pass gate attest experiments/runs/<strategy>/<run>/package \
  --gate research_gate \
  --reviewer independent-reviewer \
  --principal-type human \
  --provider human \
  --model manual-review \
  --run-id review-001 \
  --author-provider codex \
  --reviewer-provider human \
  --state-before .the-pass/runs/<run-id>/state-before.yaml \
  --state-after .the-pass/runs/<run-id>/state-after.yaml \
  --task-evidence experiments/runs/<strategy>/<run>/package/findings.json \
  --key-registry reviewer-keys.json \
  --created-at 2026-07-15T00:00:00Z \
  --output experiments/runs/<strategy>/<run>/package/reviewer_attestation.research_gate.json \
  --format json

unset THE_PASS_REVIEW_SIGNING_KEY

the-pass gate evaluate experiments/runs/<strategy>/<run>/package \
  --gate research_gate \
  --reviewer independent-reviewer \
  --ledger .the-pass/receipts.jsonl \
  --trusted-reviewers /absolute/path/to/trusted-reviewers \
  --output experiments/runs/<strategy>/<run>/package/gate_decision.research_gate.yaml \
  --format json

the-pass receipts --ledger .the-pass/receipts.jsonl --format json add-decision \
  experiments/runs/<strategy>/<run>/package/gate_decision.research_gate.yaml \
  --trusted-reviewers /absolute/path/to/trusted-reviewers
```

A run receipt proves that a run happened. It never proves that a gate passed. A gate pass requires
a valid reviewer attestation and the separate decision for the exact package ID, package path,
reviewer, policy hash, evidence fingerprints, and external reviewer trust anchor. `gate keygen`
creates a key binding but does not authorize it. Place approved registries outside the evaluated
package and provide the file or directory through `--trusted-reviewers` or
`THE_PASS_TRUSTED_REVIEWER_REGISTRY`. Ledger replay requires the same trust store but never needs
the private signing key.

## 6. Run Your Own Strategy

The supported runtime accepts a trusted local Python file. The file exposes a factory such as
`build_strategy(config)` and returns an object with a stable `strategy_id` plus
`on_event(event, context)`. It may emit only validated `SimulatedIntent` objects. The runtime
rejects path traversal, symlink escape, credential-like config, network/order imports, malformed
intents, input mutation, same-event fills, timeouts, and oversized output.

The default `trusted_local` mode contains failures and strips credentials, but it has no OS-enforced
network or filesystem denial. Only run code you trust. `hardened` mode is available only when an
operator supplies an executable sandbox launcher that enforces the request contract and writes the
matching launcher attestation. The launcher must also be authorized by an operator-controlled
policy and pass active filesystem, loopback-network, and resource-limit probes:

```bash
the-pass backtest run ... \
  --runtime-mode hardened \
  --sandbox-launcher /absolute/path/to/audited-sandbox-launcher \
  --sandbox-policy /absolute/path/to/sandbox-policy.json
```

The policy allowlists the exact launcher SHA-256 and required enforcement contract. Before every
strategy worker, The Pass runs a probe through that launcher. A self-declared attestation without
the allowlist and passing probe fails closed. The Pass does not ship a portable privileged sandbox
because enforcement differs by operating system; `trusted_local` evidence is always diagnostic and
non-promotional.

Start with the complete offline example:

```bash
WORK="$(mktemp -d)"

the-pass data ingest \
  --provider futures \
  --archive-root tests/fixtures/futures \
  --request examples/custom-strategy/fetch-request.json \
  --output "$WORK/data" --format json

the-pass backtest run \
  --descriptor examples/custom-strategy/descriptor.json \
  --strategy-spec examples/custom-strategy/strategy-spec.json \
  --events "$WORK/data/canonical-events.jsonl" \
  --data-manifest "$WORK/data/data-manifest.json" \
  --quality-report "$WORK/data/quality-report.json" \
  --execution examples/custom-strategy/execution.json \
  --workspace-root examples/custom-strategy \
  --runtime-mode trusted_local \
  --output "$WORK/package" --format json

the-pass audit reproduce "$WORK/package" \
  --output "$WORK/reproduction-report.json" --format json
```

The command runs two fresh workers. Any semantic difference blocks package creation. A completed
diagnostic command still writes `verdict: blocked`; only a separate independent gate decision may
promote the exact package. `audit reproduce` verifies every bundled input, copies only declared
strategy files into a clean temporary workspace, invokes the fixed internal runner without a shell,
and compares the rebuilt artifacts. Its reproduction specification records the exact runtime mode
and isolation evidence instead of inferring sandboxing from an import filter.

For promotion-capable parameter work, use generated purged walk-forward folds rather than
hand-selected result windows:

```bash
the-pass robustness sweep \
  --source-package "$WORK/package" \
  --descriptor descriptor.json --events canonical-events.jsonl \
  --execution execution.json --variants variants.json \
  --train-size 10000 --test-size 2000 --purge 30 --embargo 30 \
  --selected-index 2 --null-variant-index 0 \
  --stress-results stress-results.json \
  --runtime-mode hardened --sandbox-launcher /path/launcher \
  --sandbox-policy /path/sandbox-policy.json \
  --output "$WORK/robustness_report.json"
```

Every cell is retained, including failures. The v2 report binds the source package, strategy,
execution, events, variants, folds, null control, mandatory stresses, and runtime eligibility.
Validation recomputes PBO, PSR, DSR, Reality Check/SPA, null comparison, and neighboring-parameter
stability from the stored matrix.

After a separate reviewer writes passing `findings.json`, do not edit metrics or verdict files:

```bash
the-pass candidate assemble "$WORK/package" "$WORK/candidate" \
  --ledger "$WORK/ledger.jsonl" --run-id candidate-v1 \
  --created-at "2026-07-16T00:00:00Z" \
  --robustness-report "$WORK/robustness_report.json" \
  --findings "$WORK/findings.json"
```

The assembler creates a successor, derives the robustness summary and verdict links, validates the
complete package, and removes the target on failure.

If the ledger already contains any passed gate decision, add
`--trusted-reviewers /absolute/path/to/trusted-reviewers` to `candidate assemble`,
`workflow supersede`, and every later `receipts add`. This forces all mutations to replay the
existing decisions against the same operator-controlled trust anchor.

After research passage, `the-pass paper observe` can append immutable event batches. Each resume
replays all batches, verifies the previous intent/fill prefix, enforces the same strategy,
execution and risk hashes, and maintains an append-only invocation chain. It deliberately records
`elapsed_time_verified: false`; offline replay cannot manufacture a 30-day or 60-day paper window.
A worker failure after an immutable batch commit persists a frozen observation and invocation, so
the batch cannot become untracked orphan evidence.

An external engine remains supported when it preserves the same contracts. It must export a
package containing at least:

- immutable StrategySpec copy;
- data manifest and unblocked quality evidence;
- run receipt with code/config/data fingerprints;
- complete gross and net metrics;
- cost waterfall reconciled to net PnL;
- verdict report and execution assumptions;
- robustness, risk, and independent audit evidence required by the target gate.

Validate the exported package and append it through the same CLI. External engine output never
bypasses chronology, cost, reviewer, ledger, or gate checks.

## 7. Use Data Adapters Correctly

The quick decision table is in [Getting Started: Where the Data Comes From](GETTING_STARTED.md#2-where-the-data-comes-from).

- Binance Spot and Polymarket support public read-only market data.
- Futures use the Databento-compatible interface and fixture replay. Promotion requires a
  user-supplied licensed archive.
- Klines are suitable for diagnostics; fill-sensitive promotion requires trade or book evidence.
- Polymarket fees are dynamic and token-specific; never use one global flat fee.
- Paid data, provider credentials, authenticated user channels, and raw private outputs do not
  belong in the repository or evidence artifacts.

`the-pass data ingest` connects the protocol to a bounded immutable bundle. Binance and Polymarket
require explicit `--network`; futures requires `--archive-root`. A successful output contains
`request.json`, raw response, canonical JSONL, quality report, DataManifest, ingest receipt, and a
`COMMITTED` marker. An existing output path is never overwritten. Backtests must consume only the
canonical events whose fingerprint matches the supplied manifest.

For a longer interval, create the immutable chunk plan first and let `data build` resume only
verified committed chunks:

```bash
the-pass data plan \
  --id btcusdt-15m-2025 \
  --provider binance \
  --kind klines \
  --instrument BTCUSDT \
  --start-ns <inclusive-start-ns> \
  --end-ns <exclusive-end-ns> \
  --chunk-ns <chunk-width-ns> \
  --expected-interval-ns 900000000000 \
  --created-at <fixed-rfc3339-time> \
  --output dataset-plan.json \
  --format json

the-pass data build \
  --plan dataset-plan.json \
  --output data/btcusdt-15m-2025 \
  --network \
  --license-reviewed \
  --format json
```

The final `COMMITTED` dataset is fully revalidated on every resume, including event, quality,
manifest, aggregate receipt, and per-chunk fingerprints. Use `--require-cross-check` on the plan
when missing independent reference data must block promotion.

Audit source depth separately:

```bash
the-pass research evidence \
  --registry research/sources.yaml \
  --output reports/research-evidence.json \
  --format json
```

Only explicitly full-text evidence with a locator is independently eligible to support an edge
claim. Abstracts, metadata, operator material, and unspecified reviews remain visible but cannot
be silently upgraded.

## 8. Delegate To The Other Provider

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

## 9. Understand Results And Exit Codes

| Exit | Meaning |
| --- | --- |
| `0` | operation succeeded or the evaluated gate passed |
| `1` | invalid input, schema failure, missing evidence, or technical failure |
| `2` | valid `blocked`, `revise`, `kill`, `waiting`, or `frozen` research result |
| `3` | forbidden safety operation, including the public live boundary |

Exit `2` means The Pass worked and declined progression. Automation must not treat it as a crash or
rewrite the evidence to force exit `0`.

## 10. Resume Without Rewriting History

- Use `/the-pass:status` or `the-pass workflow status` first.
- Resolve the named blocker or wait condition.
- Resume through a validated workflow transition; do not edit state counters by hand.
- Never modify a package after its run receipt is recorded.
- Use `the-pass candidate assemble` for the research candidate; use `workflow supersede` for later
  paper, risk, or remediation evidence.
- Every successor receives a new run ID and package ID and must replay prerequisite gates.

## 11. Build Reports

```bash
the-pass report build --repo-root . --output-dir reports/generated/report --format json
the-pass dashboard build --repo-root . --output-dir reports/generated/dashboard --format json
```

The output is static and read-only. It can summarize evidence but cannot modify StrategySpecs,
limits, gate decisions, ledgers, or approval state.

## 12. Common Mistakes

- Expecting `/the-pass:run` without an objective to invent a new strategy instead of resuming.
- Assuming that no existing backtest means no historical market data will be needed later.
- Installing the plugin but not the `the-pass` CLI.
- Forgetting `/reload-plugins` or a new session after installing the Claude Code plugin.
- Starting with `paper_gate` before an exact research-gated package exists.
- Using the same identity for strategy owner, run owner, and reviewer.
- Treating a package-local reviewer registry as authorization instead of supplying an external
  trusted registry.
- Marking a launcher `hardened` without an allowlist policy and passing active probe.
- Editing metrics or verdict JSON instead of using `candidate assemble`.
- Editing a recorded package instead of creating a successor.
- Treating a receipt, verdict string, filename, or dashboard label as gate passage.
- Treating exit `2` as a software failure.
- Expecting synthetic examples, klines, or mid-price fills to support promotion.
- Asking an agent to apply its own patch or approve its own result.
- Supplying exchange credentials or asking the public core to place an order.

For exact command arguments, run `the-pass <group> <command> --help`. The stable machine response
and exit-code contract is documented in [CLI_CONTRACT.md](CLI_CONTRACT.md), and slash-skill
semantics are documented in [../plugin/COMMANDS.md](../plugin/COMMANDS.md).

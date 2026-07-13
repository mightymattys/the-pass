# Usable Strategy Runtime and Evidence Pipeline Plan

Status: implementation complete; release verification recorded in `reports/RELEASE_AUDIT_0.11.0.md`  
Owner: The Pass maintainers  
Target release: v0.11.0  
Safety boundary: research, replay, simulation, and read-only market data only

## 1. Purpose

The Pass already validates research artifacts, synthetic baselines, gates, receipts,
and supervised agent workflows. This plan closes the remaining product gap: a user
must be able to supply a strategy and canonical market data, run the same decision
code in backtest and paper observation, and receive deterministic evidence without
editing The Pass internals.

The release is successful when a new user can perform this supported flow:

1. write a local Python strategy factory implementing `StrategyRunner`;
2. validate its descriptor and versioned execution configuration;
3. ingest public read-only data or an offline licensed fixture;
4. run the strategy in an isolated deterministic subprocess;
5. produce a complete, non-promotional diagnostic run package;
6. resume paper observations from immutable input batches;
7. audit model, source, data, cost, and execution assumptions;
8. reproduce the result from recorded fingerprints.

This work does not create an order transport, authenticated exchange client,
credential loader, scheduler, or automatic gate approval. Those remain forbidden.

## 2. Findings That Drive This Plan

### P0: no supported custom strategy entry point

`StrategyRunner` is public, but the CLI only instantiates internal baseline names.
Users cannot currently point `backtest` or `paper` at their own strategy without
modifying package code. A plugin framework that cannot execute a user strategy is
not yet a complete strategy-testing product.

### P0: adapters are not connected to an ingest command

Binance Spot and Polymarket contain public read-only clients and the futures lane
supports local fixtures, but `the-pass data` only builds a quality report from an
already-normalized JSONL file. Discovery, fetch, raw evidence, normalization,
quality, and manifest creation need one bounded workflow.

### P0: paper execution is one-shot

The virtual paper worker accepts one static event file and exits. It does not own a
durable observation directory, deduplicate batches, enforce configuration continuity,
or prove that an earlier decision prefix stayed unchanged after resuming.

### P1: execution assumptions are hard-coded

The current worker uses five basis points of slippage, a 0.10 percent fee, and a bar
fill model. Those defaults are acceptable for synthetic controls but not as an
implicit execution model for arbitrary crypto, futures, or prediction-market runs.

### P1: real public integration evidence is too narrow

Public smoke checks prove that selected endpoints respond. They do not create a
canonical dataset and run a strategy through the complete diagnostic pipeline.

### P1: research evidence depth is not measured

The source registry distinguishes reviewed and blocked notes, but it does not report
whether a claim came from full text, an abstract, metadata, or an operator summary.
That distinction must be visible and must fail closed for promotion evidence.

### P1: model freshness is a manual assertion

Agent routing pins two or three current models per provider, as requested, but the
catalog review date is not subject to a freshness check. Local binary presence also
does not prove authenticated model access.

### P1: named automation jobs do not yet execute domain checks

The scheduler-neutral automation contract is sound, but several named jobs currently
reach a generic receipt worker. A `data_health`, `paper_observer`, `risk_monitor`,
`drift_report`, or `tca_report` run must not report `complete` unless the corresponding
domain handler inspected its required evidence and produced typed findings.

### P1: robustness is detached from strategy execution

The statistics functions correctly evaluate supplied matrices, but the supported CLI
does not build those matrices by running a preregistered user strategy across variants
and walk-forward windows. A reproducible strategy-testing workflow needs that bridge.

## 3. Locked Decisions

- A user strategy is trusted local research code. A separate process with a small
  environment allowlist, timeout, and bounded output prevents accidental credential
  inheritance and contains failures; it is not an OS sandbox and does not prove that
  trusted code cannot read files or open sockets.
- The supported v1 strategy reference is one self-contained local strategy file plus factory name.
  Arbitrary package entry points, local helper bundles, and remote code downloads are not supported;
  a multi-file strategy requires a future bundle manifest that hashes every imported file.
- The strategy file must resolve inside an explicit workspace root. Symlinks and path
  traversal outside that root are rejected. Its SHA-256 is evidence.
- A factory accepts a JSON object and returns an object with a non-empty
  `strategy_id` and callable `on_event(event, portfolio)` method.
- Backtest and paper use the same worker, strategy file, strategy config hash,
  execution config hash, simulator, event ordering, and risk policy implementation.
- Execution configuration is data, not Python: only allowlisted fill models and
  validated numeric parameters are accepted.
- A generic run is diagnostic and `blocked` by default. The CLI cannot label it a
  paper candidate or append a passing gate decision.
- Public provider ingest is opt-in network work. Default CI remains fully offline.
- Futures ingest reads only a user-supplied archive or committed synthetic fixture.
- Paper observation consumes canonical event batches written by a separate read-only
  collector. The paper worker never imports HTTP, WebSocket, exchange, or order clients.
- Resumption replays the immutable accumulated event set and verifies that the prior
  decision/fill prefix did not change. This favors evidence integrity over throughput.
- Duplicate batches are idempotent only when their fingerprints match exactly.
- Strategy, execution, risk, and dataset configuration drift starts a new observation
  or freezes the current one; it never mutates an existing history.
- Model catalogs never update themselves. A stale catalog blocks agent execution
  until a human reviews provider documentation and commits a policy update.
- No source is upgraded to full-text evidence without a locator and access-scope
  declaration. The implementation reports evidence gaps instead of inventing them.

## 4. Public Contracts

### 4.1 Strategy descriptor v1

Required JSON fields:

| Field | Contract |
| --- | --- |
| `schema_version` | integer `1` |
| `strategy_id` | stable non-empty identifier |
| `strategy_file` | relative self-contained file inside workspace root |
| `factory` | Python identifier, default `build_strategy` |
| `config` | JSON object passed to the factory |
| `asset_class` | `crypto_spot`, `futures`, or `prediction_market` |
| `owner` | accountable human or team identifier |

The runtime adds, but never trusts from input, the resolved path, source SHA-256, descriptor and
config fingerprints, and runtime version. The v1 contract deliberately rejects the stronger claim
that a multi-file dependency bundle was fingerprinted.

### 4.2 Execution configuration v1

Required fields are `schema_version`, `initial_cash`, `fill_model`, `fee_rate`, and
`slippage_bps`. Optional conservative haircuts are valid only for the corresponding
fill model. Decimal values are strings and must be finite and non-negative.

Allowlisted fill models:

- `bar_next_open`: next eligible bar open with adverse slippage;
- `market_depth`: subsequent opposing book depth, with partial rejection;
- `limit_evidence`: subsequent trade/book evidence with queue and adverse-selection
  haircuts;
- `diagnostic_midpoint`: explicitly non-promotional.

The configuration records whether its fill model can ever support promotion. A data
source fee snapshot may be compared with `fee_rate`; it does not silently override it.

### 4.3 Worker result v1

The subprocess returns one canonical JSON document containing:

- strategy identity and code hash;
- descriptor, execution, risk, and event fingerprints;
- process isolation and environment safety checks;
- signals, intents, fills, misses, rejections, costs, equity, and final portfolio;
- fill-model promotion eligibility;
- deterministic result fingerprint;
- bounded stderr metadata on failure, never environment contents.

### 4.4 Ingest bundle v1

An ingest writes to a new output directory through staging and atomic rename:

```text
raw/
canonical-events.jsonl
quality-report.json
data-manifest.json
ingest-receipt.json
request.json
COMMITTED
```

The receipt includes provider capability, request fingerprint, raw fingerprints,
normalizer code version, canonical fingerprint, quality result, cost snapshot, and
cross-check evidence. Existing non-identical output is never overwritten.
The quality report carries the exact canonical event fingerprint and row count; generic packaging
requires both to match the manifest-bound event set.
Historical Binance bars use provider close time as conservative decision availability;
the later HTTP observation time remains separate transport evidence in the receipt.

### 4.5 Paper observation directory v1

```text
observation.json
batches/<batch-id>.jsonl
runs/<sequence>.json
current-result.json
invocations.jsonl
```

`observation.json` pins all configuration and code fingerprints. Each invocation
record links to the previous record hash. A new batch is committed before replay;
failed replay freezes the observation and preserves the input evidence.

## 5. CLI Surface

### Generic backtest

```bash
the-pass backtest run \
  --descriptor strategy.json \
  --strategy-spec strategy-spec.json \
  --events canonical-events.jsonl \
  --data-manifest data-manifest.json \
  --quality-report quality-report.json \
  --execution execution.json \
  --workspace-root . \
  --output runs/example \
  --timeout-seconds 60
```

The command cross-validates the descriptor, StrategySpec, events, manifest, and quality
report; pre-registers a one-variant search space; invokes two fresh worker processes;
requires identical semantic fingerprints; builds a diagnostic package; validates it;
and writes a run receipt.
Exit `0` means the run completed and artifacts validate, not that a gate passed.

### Data ingest

```bash
the-pass data ingest --provider futures --archive-root ...
the-pass data ingest --provider binance --network ...
the-pass data ingest --provider polymarket --network ...
```

Network providers reject execution unless `--network` is explicit. The futures lane
requires `--archive-root`. Provider-specific request parameters are loaded from a
JSON request file and validated by the selected adapter.

### Resumable paper observation

```bash
the-pass paper observe \
  --descriptor strategy.json \
  --events batch-001.jsonl \
  --batch-id batch-001 \
  --execution execution.json \
  --risk-policy risk-policy.json \
  --observation-dir paper/example \
  --workspace-root . \
  --observation-time-ns 1700000000000000000 \
  --max-staleness-ns 60000000000 \
  --max-clock-skew-ns 5000000000 \
  --max-outage-gap-ns 120000000000
```

### Evidence and agent checks

```bash
the-pass research evidence --registry research/sources.yaml --output report.json
the-pass agents catalog-check --as-of 2026-07-13
```

Catalog check exit `2` means a valid but stale/blocked policy. Authenticated provider
access remains an explicit execution smoke, never an assumption inferred from a
binary being installed.

## 6. Implementation Phases

### U0: plan and contract freeze

Deliverables:

- this plan;
- a threat-boundary review for custom code and data ingestion;
- stable v1 JSON examples for strategy and execution configuration;
- explicit compatibility statement for existing baseline and paper commands.

Acceptance:

- no unresolved technology choice or `TBD`;
- no path can send or sign an order;
- all new commands follow the existing JSON envelope and exit-code contract.

Kill condition: stop implementation if generic execution would require credentials,
authenticated market access, or mutation of existing ledger evidence.

### U1: isolated custom strategy runtime

Deliverables:

- descriptor and execution config parsers;
- workspace path and symlink containment checks;
- source/config/event fingerprinting;
- credential-free subprocess worker with timeout and output limit;
- generic backtest CLI;
- example strategy, descriptor, execution config, and canonical events;
- diagnostic package metadata that records actual user inputs instead of describing
  them as synthetic built-ins.

Acceptance tests:

- valid custom strategy completes twice with identical fingerprints;
- factory errors, invalid return objects, NaN/negative values, missing strategy ID,
  timeout, oversized output, and malformed JSON fail with exit `1`;
- path traversal and symlink escape are rejected;
- sensitive environment variables do not reach the worker;
- credentials are not inherited and the report makes no unsupported sandbox claim;
- two fresh worker runs are compared and nondeterminism blocks packaging;
- same-event fills remain impossible;
- generic packages are blocked by default and validate structurally.

Kill condition: any reproducible way for untrusted paths or credentials to cross the
worker boundary blocks release.

### U2: canonical ingest workflow

Deliverables:

- provider-neutral ingest service;
- CLI wiring for Binance, Polymarket, and futures fixture/archive;
- atomic bundle commit and immutable-output semantics;
- raw and normalized fingerprints;
- quality report, manifest, cost snapshot, and cross-check capture;
- deterministic offline fixtures for all provider contracts.

Acceptance tests:

- fixture ingest produces identical canonical fingerprints twice;
- mutation of raw input changes downstream fingerprints;
- missing intervals, ordering mutations, invalid books, and provider truncation block
  promotion impact as specified by quality policy;
- network providers require `--network`;
- futures requires a local archive and never logs credentials;
- an existing non-identical output directory is preserved and causes failure.

Kill condition: silent raw overwrite, normalization without raw evidence, or a network
request in default CI blocks release.

### U3: resumable paper observer

Deliverables:

- immutable batch store;
- append-only invocation hash chain;
- replay-based state reconstruction;
- prefix stability check for prior decisions and fills;
- duplicate and conflicting batch handling;
- configuration drift detection;
- freeze-closed data-health behavior;
- cumulative observation counters and window status.

Acceptance tests:

- two sequential batches produce one cumulative deterministic result;
- replaying the same batch is idempotent;
- the same batch ID with different bytes freezes/fails;
- strategy code, execution config, or risk policy drift cannot continue an observation;
- stale data, clock skew, outage gaps, and risk breaches freeze closed;
- interruption before atomic state replacement leaves the previous snapshot readable;
- no network client or credential appears in the worker process.

Kill condition: resumption can change the historical decision/fill prefix without a
freeze and explicit incident artifact.

### U4: execution and cost evidence

Deliverables:

- versioned execution config and allowlisted model factory;
- explicit fee, spread, slippage, partial-fill, missed-fill, and rejection evidence;
- provider cost-snapshot comparison report;
- promotion eligibility flag carried into package and gate validation;
- documentation for venue-specific configuration ownership.

Acceptance tests:

- accounting conservation holds for every allowlisted fill model;
- midpoint or bar-only diagnostics cannot claim book-replay evidence;
- Polymarket dynamic fee snapshots are timestamped and compared by token ID;
- missing Binance/futures fee evidence remains a blocker, not a guessed constant;
- impossible fills and cost-waterfall mismatches are rejected.

Kill condition: an implicit fee default can be mistaken for observed venue costs.

### U5: real public diagnostic smoke

Deliverables:

- opt-in script/workflow that ingests a bounded public Binance and Polymarket sample;
- a diagnostic backtest/scanner package built from each sample;
- endpoint, timestamp, fingerprint, quality, and cost evidence;
- artifact retention without committing provider payloads that violate terms.

Acceptance:

- failures are classified as endpoint, license, schema, quality, or strategy failures;
- the workflow cannot run in ordinary offline CI;
- public samples remain diagnostic and cannot pass a promotion gate.

Kill condition: provider terms are not reviewed, payload retention is unclear, or a
smoke path requires authentication.

### U6: research evidence maturity

Deliverables:

- evidence-scope report for every source note;
- scope classes: `full_text`, `abstract`, `metadata`, `operator_material`, `blocked`;
- locator requirement for full-text claims;
- counts by topic, status, scope, recency, and linked hypotheses;
- gate blocker when a candidate relies only on abstract/metadata/operator material.

Acceptance:

- the report never promotes evidence based on the existing `reviewed` label alone;
- inaccessible material stays blocked;
- no copyrighted full text is copied into the repository;
- existing notes remain readable while evidence gaps become explicit.

Kill condition: the migration invents page numbers, access scope, or verification that
was not actually performed.

### U7: model policy freshness and access truth

Deliverables:

- catalog maximum-age policy;
- deterministic catalog freshness command;
- maintenance workflow check;
- explicit distinction among binary presence, authentication check, model access, and
  successful task execution;
- documentation for human catalog refresh against provider primary sources.

Acceptance:

- only two or three current models per provider remain allowed;
- Codex models older than the configured 5.6 floor are rejected;
- stale review date exits `2` and blocks external-agent execution;
- `doctor` never claims model access without a provider call;
- access failures are evidence and never silently fall back to an older model.

Kill condition: routing silently changes provider/model or lowers the model floor.

### U7A: executable automation handlers

Deliverables:

- a registry mapping every supported automation job to a domain-specific handler;
- required-input contracts for data health, baselines, gate check, paper observation,
  risk monitoring, drift, TCA, corpus refresh, and weekly summary;
- typed `complete`, `blocked`, `failed`, and `duplicate` results;
- removal of any path where a generic receipt alone proves domain success.

Acceptance:

- each job has a positive fixture and a failing or blocking fixture;
- missing evidence cannot produce `complete`;
- retry remains limited to idempotent fetch/report work;
- paper, risk, and gate jobs call existing validated domain functions;
- every output identifies inspected artifacts and their fingerprints.

Kill condition: a named domain job can return `complete` without reading its declared
inputs or producing domain findings.

### U7B: strategy-driven robustness workflow

Deliverables:

- a preregistered variant descriptor format;
- deterministic execution of every variant and split through the custom strategy
  worker;
- anchored and rolling walk-forward result matrix generation;
- optional purging/embargo derived from declared holding horizon;
- direct handoff into PBO, PSR/DSR, sensitivity, stress, and risk reports;
- a terminal verdict for every registered variant, including failures.

Acceptance:

- no variant may be omitted after preregistration;
- the create-only registration artifact must be durable before the first worker call;
- split chronology and receive-time rules are validated before execution;
- two clean sweeps produce identical matrices and fingerprints;
- failed variants remain in evidence and cannot be silently filtered;
- a seeded null control does not gain systematic net edge through selection.

Kill condition: the workflow selects a winner before recording the full search space or
can exclude failed variants from multiple-testing corrections.

### U8: independent audit and release

Deliverables:

- unit, property-style, golden, CLI, and end-to-end tests;
- offline full suite on Python 3.9 and 3.12;
- opt-in network smoke result;
- safety scan proving absence of live order paths and secrets;
- updated README, implementation index, completion audit, changelog, and version;
- independent reviewer findings with disposition;
- GitHub branch, pull request, green checks, merge to `main`, and release evidence.

Acceptance:

- lint, tests, package build, install smoke, artifact validation, ledger verification,
  docs checks, plugin checks, and safety scans are green;
- a clean temporary checkout reproduces the custom-strategy example;
- no P0/P1 finding is open;
- claims distinguish implemented framework capabilities from completed market evidence;
- worktree is clean after publication.

## 7. Test and Simulation Matrix

| Layer | Required scenarios |
| --- | --- |
| Descriptor | valid, missing key, unknown key, bad factory, path escape, symlink escape |
| Execution | every fill model, invalid decimals, partial fills, no liquidity, diagnostic eligibility |
| Worker | success, strategy exception, timeout, oversized result, credential stripping |
| Determinism | repeated run, reordered input, duplicate event, changed code/config/input |
| Data | three adapter fixtures, raw mutation, quality mutation, immutable commit |
| Paper | two batches, duplicate batch, conflicting batch, restart, prefix divergence, drift |
| Research | each evidence scope, missing locator, blocked URL, registry count reconciliation |
| Agents | fresh/stale catalog, unsupported model, missing binary, no access assertion |
| E2E success | custom strategy → fixture ingest → backtest → package validation → receipt |
| E2E failure | incomplete data, optimistic fill, stale paper input, strategy timeout |
| Safety | secret scan, live-import scan, offline CI network denial, path containment |

The test suite must use deterministic timestamps and Decimal values. Network tests are
marked and excluded by default. Any test that only checks that a file exists is
insufficient when a semantic fingerprint or accounting identity can be asserted.

## 8. Rollout and Compatibility

- Existing `backtest baseline` and `paper run` remain available for compatibility.
- New commands are additive in v0.11.0.
- Generic packages remain schema v2 compatible where possible; runtime-specific
  evidence is recorded in supplemental files before any schema-v3 migration.
- No existing immutable package or ledger row is rewritten.
- Public plugin skills route strategy testing to `backtest run` when a descriptor is
  supplied and retain baseline behavior only for controls.
- A rollback removes new command exposure but leaves generated evidence readable.

## 9. Completion Semantics

Repository implementation may be marked complete only when U0-U4 and U6-U8, including
U7A and U7B, pass in
offline CI. U5 is complete only after an opt-in public smoke succeeds under reviewed
provider terms. A real strategy is not a paper candidate merely because the framework
release is complete.

These external-evidence states remain honestly blocked until supplied:

- licensed futures history;
- long-lived Polymarket raw archive and manual resolution review;
- the required 30/60-day or signal/fill paper observation window;
- independent promotion review;
- any live-capability ADR.

The implementation report must therefore use two separate conclusions:

1. `framework_status`: whether the testing machinery is green and usable;
2. `candidate_status`: whether a particular strategy has enough market evidence.

## 10. Final Definition of Done

- A custom strategy can run without changing The Pass source.
- The same strategy code runs in backtest and resumable paper observation.
- Data enters through a provider-neutral immutable ingest bundle.
- Execution and cost assumptions are explicit, versioned, fingerprinted, and visible.
- Every completed run reaches a terminal result or a typed failure; an agent cannot
  stop early and call an incomplete run successful.
- Agent orchestration may use Codex and Claude under current-model policy, but models
  cannot approve their own work or bypass artifact gates.
- Offline CI is deterministic and green on supported Python versions.
- Public network work is opt-in, read-only, bounded, and diagnostic.
- No live order transport, authenticated order client, or credential path exists.
- Documentation and GitHub release claims match tested behavior exactly.

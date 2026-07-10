# Build Plan

This is the implementation order for The Pass. The goal is to build the public plugin
product first, not a trading strategy.

## Phase 0: Product Contract Freeze

Status: implemented.

Deliverables:

- Accepted ADRs for product scope, storage, engine neutrality, providers, risk governance,
  public distribution, and artifact schemas.
- Plugin manifest and skill folders.
- Public repo policy, security policy, release checklist, and CI.
- Artifact templates and schemas.
- Synthetic golden path example.

Gate:

- `python3 scripts/validate_public_repo.py` passes.
- Plugin validator passes.
- README points to the build plan, lifecycle, command contracts, adapters, schemas, and
  example workflow.

## Phase 1: Artifact Validator CLI

Status: implemented.

Build:

- `the-pass validate <file>` for one artifact.
- `the-pass validate-package <dir>` for an experiment package.
- YAML and JSON input support.
- Schema version detection.
- Human-readable error output.

Done when:

- CLI can validate individual JSON/YAML artifacts.
- CLI can validate full run packages.
- The synthetic example package validates.
- CI runs package validation and unit tests.

Kill or revise when:

- Validation requires hidden state outside the artifact package.
- Gate-critical fields remain free text that cannot be checked.

## Phase 2: Receipt Ledger

Status: implemented.

Build:

- Append-only run receipt ledger.
- Deterministic package IDs.
- Artifact fingerprinting.
- `the-pass receipts` summary.

Done when:

- A package can be reconstructed from ledger entries and artifact paths.
- Receipts show strategy ID, gate, verdict, data manifest, cost report, and open blockers.
- Ledger hash-chain verification detects silent edits.
- CI exercises add, verify, and summary commands.

Kill or revise when:

- Receipts can be edited silently.
- Runs cannot be traced back to exact data and config.

## Phase 3: Skill Implementation

Status: implemented.

The original eleven-skill surface was consolidated by ADR-0009. The implemented public order is:

1. `run`
2. `research`
3. `test`
4. `review`
5. `paper`
6. `plate`
7. `status`

Done when:

- Each skill has documented inputs, outputs, editable paths, blocked paths, and exit states.
- Each skill emits or updates structured artifacts rather than only prose.
- `review` can block promotion from missing or weak evidence.
- `run` enforces a bounded, resumable stage queue to one selected non-live gate.

Kill or revise when:

- A skill can claim a gate passed without artifacts.
- A skill can create or imply live trading approval.

## Phase 4: Synthetic Golden Path

Status: implemented.

Build:

- Public-safe synthetic breakout dataset or fixture.
- Source note, StrategySpec, data manifest, run receipt, metrics report, cost waterfall, and
  verdict report.
- One intentionally bad/random baseline that is killed.
- One non-promotional diagnostic run that demonstrates the workflow.

Done when:

- The example can run in CI without external credentials or paid data.
- The example does not imply real edge.
- Every artifact validates.

Kill or revise when:

- The example depends on live APIs, private data, paid data, or unstable external state.

## Phase 5: Adapter SDK

Status: implemented.

Build:

- `adapter.yaml` schema.
- Adapter mode checks: diagnostic, research, paper, live-capable.
- Provider/license checklist.
- Timestamp, cost, fill, settlement, and risk policy checks.

Done when:

- A dummy adapter validates.
- A crypto/futures/prediction-market adapter can be described without changing core code.
- Non-compliant adapters are blocked before research gates.

Kill or revise when:

- Adapter-specific logic leaks into core gate logic.

## Phase 6: First Real Adapter

Status: implemented.

Choose one adapter only after Phases 1-5 pass. The adapter should be public-safe and useful
for testing the framework, not for publishing private edge.

Default recommendation:

- Start with a synthetic adapter, then a crypto public-data diagnostic adapter.
- Keep futures, prediction markets, options, and live-capable adapters behind explicit ADRs.

Done when:

- Adapter artifacts validate.
- Provider licensing and public data boundaries are documented.
- The adapter can be removed without breaking core workflow.

## Non-Goals Before Phase 6

- Real order placement.
- Broker/exchange credentials.
- Live trading automation.
- Paid data ingestion as a public fixture.
- Proprietary strategy optimization.
- Sub-100ms execution strategies.

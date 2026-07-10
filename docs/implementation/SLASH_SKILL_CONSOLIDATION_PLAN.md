# Slash Skill Consolidation and Run Orchestrator Plan

Status: implemented and independently verified.
Approved and completed: 2026-07-10.
Target release and plugin interface: `0.8.0`.
Final evidence: [slash-skill consolidation audit](../../reports/SLASH_SKILL_CONSOLIDATION_AUDIT_2026-07-10.md).

## 1. Objective

Reduce The Pass from eleven user-facing slash skills to seven coherent entry points without
removing any research, validation, gate, audit, paper, or safety capability. Add one primary
command, `/the-pass:run`, that advances a strategy through the complete evidence workflow as far
as current evidence and hard gates allow.

The target public skill API is:

1. `/the-pass:run`
2. `/the-pass:research`
3. `/the-pass:test`
4. `/the-pass:review`
5. `/the-pass:paper`
6. `/the-pass:plate`
7. `/the-pass:status`

The granular Python CLI remains unchanged. Automation and CI need composable commands; users need
a smaller decision surface. Consolidating slash skills must not collapse the underlying ownership
or gate boundaries.

## 2. Reference Model and Deliberate Differences

The design adopts the useful orchestration properties of
[`tomascupr/sous-chef` `/serve`](https://github.com/tomascupr/sous-chef/blob/main/skills/serve/SKILL.md):

- one default end-to-end entry point;
- explicit stage composition instead of one monolithic prompt;
- a durable state file outside conversation memory;
- bounded retries and remediation;
- independent review before final verification;
- one final report after the line stops;
- honest termination on hard blockers.

The Pass cannot copy the software-delivery semantics literally. Trading research has evidence
windows and approval boundaries that may take days or months. `/the-pass:run` therefore means
"advance through every currently executable stage and stop at the first evidence, reviewer, time,
or safety boundary." It never means:

- fabricate an observation window;
- promote a strategy because commands executed successfully;
- let the strategy owner act as independent reviewer;
- turn a framework capability gate into a candidate pass;
- approve or send a live order.

## 3. Current-State Audit

The repository currently exposes eleven skills and 837 lines of skill instructions:

`mise`, `research`, `spec`, `screen`, `backtest`, `taste`, `refire`, `simmer`, `paper`, `plate`,
and `receipts`.

Strengths to preserve:

- uniform front matter and required sections;
- schema-backed outputs and stable exit states;
- immutable run packages and hash-chained receipts;
- independent review and exact gate decisions;
- fail-closed paper and live boundaries;
- explicit editable and blocked paths.

Problems to fix:

- users must understand internal stations before they can start;
- `research`/`spec`, `screen`/`backtest`, and `refire`/`simmer` expose implementation detail;
- current skills mostly validate artifacts but do not consistently invoke the implemented CLI
  groups for data, features, screens, backtests, robustness, risk, paper, and reporting;
- `taste` advertises every gate but hard-codes `research_gate` in its command example;
- receipt writing is optional-looking even though it is a mandatory audit function;
- there is no resumable orchestration state or end-to-end public command.

## 4. Public Skill Contracts

### 4.1 `run`: default orchestrator

Use for a new idea, existing StrategySpec, existing package, or resumable workflow. It performs
preflight, selects the next legal stage, applies the specialist contract, records state and
receipts, and continues until its target is reached or a hard boundary stops it.

Inputs:

- idea, source, StrategySpec, package, or existing run-state path;
- optional target gate: `research_gate`, `paper_gate`, or `risk_review`;
- mandatory strategy/run owner identifier and an independent reviewer identifier before any
  promotion review;
- optional budget override within the fixed maxima.

Default target behavior:

- a new idea targets `research_gate`;
- a package with a passed `research_gate` targets `paper_gate` and may stop `waiting` during its
  observation window;
- an active paper observation targets and resumes toward `paper_gate`;
- a package with a passed `paper_gate` targets `risk_review`;
- an explicit target may move forward but never skip prerequisites;
- `live_gate` is not a valid target in the public plugin.

Exit states:

- `complete`: requested non-live target has a recorded passing gate decision;
- `waiting`: valid external evidence or an observation window is not yet complete;
- `blocked`: evidence, reviewer, data, tooling, or safety requirements prevent progress;
- `killed`: the hypothesis hit a declared kill condition.

### 4.2 `research`: source intake plus specification

Merge the old `research` and `spec` skills. The skill supports two modes selected from input:

- `source`: review material and produce source notes plus hypotheses;
- `spec`: formalize a hypothesis into a StrategySpec;
- `auto`: perform both when sufficient evidence exists.

Research reading cannot prove statistical edge. A StrategySpec remains immutable after its first
run. Missing falsifiability, data timing, execution, cost, risk, done, or kill fields blocks
`research_ready`.

Exit states: `research_ready`, `rejected`, `blocked`.

### 4.3 `test`: screen plus backtest

Merge the old `screen` and `backtest` skills. Modes:

- `screen`: fast preregistered diagnostic;
- `backtest`: deterministic event simulation and complete package;
- `auto`: screen first, then backtest only after `backtest_candidate`.

The skill must use the implemented `data`, `features`, `screen`, and `backtest` CLI groups where
their input contracts fit. A screen cannot claim promotion. A backtest writes a run receipt even
when its verdict is blocked, revised, or killed.

Exit states: `complete`, `rejected`, `revise`, `blocked`.

### 4.4 `review`: independent review and candidate gate evaluation

Rename and expand `taste`. It is read-only with respect to strategy implementation, source data,
and strategy thesis. It may write findings, verdicts, audit reports, risk evidence, and gate
decisions.

Modes are selected by target gate:

- `research_gate`: package, execution, robustness, risk, and reproduction review;
- `paper_gate`: observation-window and divergence review;
- `risk_review`: approval-pack, limits, monitoring, rollback, and incident-readiness review;
- `live_gate`: always forbidden in the public plugin.

The reviewer identifier must differ from StrategySpec owner and run owner. Missing owners block
promotion rather than weakening this comparison. Independence is enforced by package/gate code at
`research_gate`, `paper_gate`, and `risk_review`, not only by skill prose. If an independent review
context is unavailable, the result is `blocked`; `/run` may not silently self-review.

Exit states: `passed`, `blocked`, `revise`, `kill`, `forbidden`.

### 4.5 `paper`: isolated observation

Keep separate because observation is a safety and time boundary. It prepares or resumes the paper
plan, runs only the virtual worker, records divergence and incidents, and fails closed on stale
data, clock skew, outage, or risk breach.

Exit states: `paper_ready`, `waiting`, `blocked`, `frozen`.

### 4.6 `plate`: human decision package

Keep separate because packaging evidence is not approval. It runs after `paper_gate` and before
the independent `risk_review` gate. It consumes risk evidence, exact config hash, limits,
monitoring, rollback, and incident runbook, then creates the approval pack and config diff that
`risk_review` requires. Every human decision remains pending. `live_gate` cannot be passed or
simulated.

Exit states: `packaged`, `blocked`, `forbidden`.

### 4.7 `status`: receipts, blockers, and read-only reporting

Rename and expand `receipts`. It verifies the ledger before summarizing, reports the current stage,
last valid gate, open blockers, next action, incidents, and candidate/framework state, and may
build the static report or dashboard.

Exit states: `summarized`, `blocked`.

## 5. Migration Map

| Existing public skill | Target | Migration rule |
| --- | --- | --- |
| `mise` | `run` preflight | Always executed before a new run; not user-facing |
| `research` | `research` | Retained and expanded |
| `spec` | `research` spec mode | No separate public command |
| `screen` | `test` screen mode | No separate public command |
| `backtest` | `test` backtest mode | No separate public command |
| `taste` | `review` | Renamed and made gate-aware |
| `refire` | `run` remediation | Internal, finding-scoped repair only |
| `simmer` | `run` remediation loop | Internal, bounded by gate and progress rules |
| `paper` | `paper` | Retained and expanded |
| `plate` | `plate` | Retained and hardened |
| `receipts` | `status` | Renamed; receipt writing becomes a mandatory stage side effect |

No deprecated wrapper skills remain under `skills/`, because each folder is exposed as another
slash command. Migration is documented in README and command documentation.

## 6. `/the-pass:run` State Machine

### 6.1 Durable local state

Each invocation creates or resumes:

```text
.the-pass/runs/<run-id>/state.yaml
```

`.the-pass/` is ignored by git. Promotion evidence remains in normal packages and the append-only
ledger; the run state is operational memory, not evidence and not a gate decision.

Required state fields:

```yaml
schema_version: 1
run_id: <stable id>
strategy_id: <id or pending>
objective: <one line>
target_gate: research_gate|paper_gate|risk_review
strategy_owner: <identifier>
run_owner: <identifier>
reviewer: <different identifier or null>
started_at: <UTC RFC-3339>
updated_at: <UTC RFC-3339>
stage: <pipeline stage>
status: in_progress|waiting|blocked|killed|complete
transitions_used: <integer>
remediation_laps: <integer>
no_progress_laps: <integer>
package_path: <path or null>
package_id: <id or null>
ledger_path: <path>
evidence_paths: []
blockers: []
next_action: <one line>
```

State is rewritten atomically after every transition. On resume, `/run` validates the referenced
package, recomputes its package ID, and verifies the complete ledger hash chain and referenced
artifact bytes before trusting the recorded stage. Conversation text is never the only record of
progress. A blocked run requires an explicit resume transition after its blocker is resolved;
`killed` and `complete` remain terminal.

A deterministic `the_pass.orchestration` runtime and additive `the-pass workflow
start|advance|status|supersede` CLI group own state parsing, validation, atomic persistence,
transition selection, budget counters, resume checks, and safe creation of a new mutable package
from an immutable predecessor. Skills must use this runtime; they must not update state or clone
recorded packages with ad hoc text replacement. This runtime is operational and does not create
promotion evidence.

### 6.2 Stages

| Stage | Owner role | Required evidence | Success transition | Stop transition |
| --- | --- | --- | --- | --- |
| `preflight` | orchestrator | plugin, CLI, policies, writable paths | `research` or detected resume stage | `blocked` |
| `research` | researcher | reviewed notes, hypothesis, StrategySpec | `screen` | `blocked|killed` |
| `screen` | implementer | preregistered grid, quality evidence, screen report | `backtest` | `revise|blocked|killed` |
| `backtest` | implementer | complete package and run receipt | `robustness` | `revise|blocked|killed` |
| `robustness` | stats auditor | OOS, PBO/DSR, stress, sensitivity | `review_research` | `revise|blocked|killed` |
| `review_research` | independent reviewer | findings, audit, reproducibility | `research_gate` | `revise|blocked|killed` |
| `research_gate` | gate evaluator | exact package and policy hash | `paper_prepare` or `complete` | `blocked` |
| `paper_prepare` | paper operator | plan, observer config, thresholds | `paper_observe` | `blocked` |
| `paper_observe` | paper operator | active observation manifest | `review_paper` | `waiting|frozen|blocked` |
| `review_paper` | independent reviewer | completed window and divergence | `paper_gate` | `revise|blocked|killed` |
| `paper_gate` | gate evaluator | exact paper evidence and prior gate | `risk_prepare` or `complete` | `blocked` |
| `risk_prepare` | risk operator | risk policy/report, scenarios, limits | `plate` | `revise|blocked|killed` |
| `plate` | packager | approval pack, config diff, pending human decisions | `review_risk` | `blocked|forbidden` |
| `review_risk` | independent risk reviewer | packaged risk and operations evidence | `risk_review` | `revise|blocked|killed` |
| `risk_review` | gate evaluator | exact approval package and prior paper gate | `complete` | `blocked|forbidden` |

`complete` means the requested target was reached. It does not mean live approval.

### 6.3 Queue behavior

Within one invocation, `/run` repeatedly:

1. reads and verifies state;
2. selects the next stage from machine-readable pipeline policy;
3. follows the matching specialist skill contract;
4. runs the strongest relevant CLI checks itself;
5. records artifacts and appends the immutable run or decision receipt;
6. atomically updates state;
7. continues without asking unless a hard boundary is reached.

It sends concise progress updates at stage boundaries. It does not ask for routine confirmation
between stages.

### 6.4 Immutable package progression

Scientific and operational evidence in an artifact package is frozen as soon as any ledger
records it. Later stages never edit or relabel that recorded evidence. The only allowed later
file is a new append-only `gate_decision.*` governance attachment produced by the evaluator;
gate decisions are deliberately excluded from package identity. Progress that needs additional
research, paper, risk, config, approval, or audit evidence creates a superseding package with a
new run receipt and package ID:

1. copy the required prior evidence into a new package root;
2. assign a new run ID and run-receipt ID;
3. record `supersedes_package_id` and the prior package fingerprint in the new run receipt;
4. add robustness, review, paper, risk, or approval artifacts only to the new package;
5. finalize all files and validate the new package;
6. append the new run receipt to the shared ledger and immediately verify the ledger;
7. re-evaluate and append every prerequisite gate against that exact new package in canonical
   order, then evaluate the target gate.

The backtest package's own local ledger remains valid and historical. `/run` never mutates it into
a paper candidate. This superseding-package rule applies to normal progression and remediation.

Prior gate decisions are not inherited by package name, strategy ID, or prose linkage. A finalized
paper successor is recorded, then receives a fresh `research_gate` decision before `paper_gate`.
A finalized risk successor receives fresh `research_gate` and `paper_gate` decisions before
`risk_review`. This preserves the existing exact-`package_id` gate invariant while allowing
immutable package progression.

Paper and risk artifacts may have canonical working copies under `experiments/paper/` and
`reports/`, but every artifact used by `the-pass gate evaluate` must also be copied into the exact
superseding package root before package finalization. The gate evaluator does not search external
directories or follow unverified prose links.

Package identity fingerprints package-root paper plans, observation manifests, divergence
reports, risk policies/reports, config diffs, approval packs, incidents, and gate-specific audit
reports. `risk_report.package_id` is normalized only while calculating the identity to break its
self-reference; its complete bytes are still fingerprinted by run and gate-decision ledger
entries. `the-pass workflow fingerprint` computes the stable identity before append.

## 7. Budgets, Remediation, and Convergence

Defaults and hard maxima:

- maximum 20 stage transitions per invocation;
- maximum 3 finding-scoped remediation laps per candidate gate;
- stop after 2 consecutive no-progress laps;
- no retry of gate decisions;
- retries only for idempotent fetch/report operations;
- every failed launch or remediation attempt consumes its budget slot.

Remediation procedure:

1. start only from confirmed findings with evidence paths;
2. freeze the thesis, registered search space, and original run package;
3. change only finding-owned files;
4. create superseding artifacts or a new run, never rewrite receipts;
5. rerun the exact failed check;
6. request independent review again when promotion evidence changed;
7. stop on repeated failure signature, unchanged evidence fingerprint, or budget exhaustion.

## 8. Independent Review and Gate Integrity

- Implementer, StrategySpec owner, and independent reviewer identifiers are recorded separately.
- `/run` may use an available independent subagent or reviewer process only when it receives a
  distinct reviewer identity and read-only review scope.
- Without such a reviewer, state becomes `blocked` with next action `invoke /the-pass:review in an
  independent review context`.
- A run receipt never implies gate passage.
- Only `the-pass gate evaluate` creates a gate decision.
- Only `the-pass receipts add-decision` records that decision.
- Later gates require exact prior `package_id` membership in the ledger.
- Framework milestone status is never used as candidate evidence.
- Missing StrategySpec or run owners block every candidate gate that requires independent review.
- Owner/reviewer inequality is checked by the gate evaluator for all promotion gates and covered
  by regression tests for `research_gate`, `paper_gate`, and `risk_review`.
- `paper_gate` requires `audit_report.paper_gate.*`; `risk_review` requires
  `audit_report.risk_review.*`. Each report must pass, match the invoked reviewer and gate, and
  contain no unresolved promotion blocker.
- Prior-gate membership is accepted only from a ledger whose hash chain and every referenced
  artifact fingerprint verify.
- Workflow state may enter `complete` only when that same verified ledger contains a passed target
  gate decision for the exact state package ID.

## 9. Safety Boundary

The consolidation must preserve or strengthen these invariants:

- no credential loader, authenticated order client, or real order transport;
- public Binance and Polymarket access remains read-only;
- futures remains diagnostic without a user-supplied licensed archive;
- paper runs in the isolated virtual process;
- risk limits are strategy-independent;
- incidents and stale data freeze progression;
- `live_gate` is rejected with forbidden status and CLI exit code 3;
- `plate` leaves all human decisions pending;
- `/run` cannot target, unlock, or emulate live trading.

## 10. Machine-Readable Pipeline Policy

Add `config/skill-pipeline.v1.yaml` as the source of truth for:

- exactly seven public skills;
- stage order and owner role;
- relevant CLI command groups;
- success, waiting, blocked, revise, kill, and forbidden transitions;
- gate IDs and reviewer requirements;
- transition and remediation budgets;
- local state path and required fields;
- locked live behavior.

Each executable stage declares an exact CLI mapping: command group and subcommand, required
inputs, generated outputs, accepted exit codes, and a capability predicate. Existence in top-level
`--help` is insufficient. The validator executes parser-level contract tests for every mapping.

The public-repo validator must reject:

- an eighth public skill;
- a missing required skill;
- undocumented exit-state drift;
- a stage that skips a prerequisite;
- a promotion stage without an independent reviewer;
- a `live_gate` target or pass transition;
- a retryable gate decision;
- removed slash-command names in current public docs;
- referenced CLI groups that do not exist.

## 11. Documentation and Versioning

Update:

- `.codex-plugin/plugin.json` and Python package metadata to `0.8.0` with new default prompts;
- `README.md` command table and lifecycle;
- `docs/plugin/COMMANDS.md` as the seven-command public contract;
- `docs/implementation/SKILL_CONTRACTS.md` with consolidated ownership;
- `docs/implementation/ARTIFACT_LIFECYCLE.md` with new public names;
- `CHANGELOG.md` under `Unreleased`;
- public validation counts and any audit text that enumerates slash skills.
- add ADR-0009 to supersede the eleven-command interface portions of ADR-0001 and ADR-0006;
- update the main research plan's current command vocabulary while retaining its historical
  phase record as explicitly superseded.

The Python and plugin versions move together to `0.8.0`. The Python CLI receives the additive
`workflow` group and gate independence hardening; artifact schema compatibility remains v2.

### 11.1 Standalone skill ledger rules

- `test` finalizes a package, appends the run entry, handles duplicate as idempotent success, and
  verifies the ledger before returning `complete`, `rejected`, or `blocked`.
- `review` evaluates the selected gate, appends the decision when valid, handles duplicate as
  idempotent success, and verifies the ledger before returning `passed`.
- `paper` and `plate` create superseding packages, append their run entries after finalization,
  and verify the ledger.
- append or verification failure forces `blocked`; no skill may report success from an unrecorded
  promotion artifact.
- `status` never modifies existing entries and validates any generated receipt summary.

## 12. Test Matrix

### Static and contract tests

- exactly seven skill directories and names;
- front matter contains only `name` and `description`;
- all required sections exist;
- skill exit states match command docs and pipeline policy;
- all local references resolve;
- migration aliases do not remain exposed;
- plugin manifest points to the skill root and version `0.8.0`;
- every pipeline contract's sample argv parses, accepted exit codes are valid, every top-level
  group has an executed JSON-envelope test, and domain suites exercise success and fail-closed
  behavior. Capability predicates remain explicit runtime preconditions evaluated by the owning
  skill because they depend on real input artifacts, not static parser state.

### State-machine tests

- new idea starts at preflight/research;
- existing package resumes without repeating completed evidence;
- failed screen cannot advance to backtest;
- missing quality evidence blocks testing;
- run receipt is appended for killed and blocked runs;
- research pass requires independent review and a separate gate decision;
- paper and risk reviewers equal to either owner are blocked, including when an owner is missing;
- paper cannot start without exact research-gate ledger membership;
- incomplete observation returns waiting, not pass;
- repeated no-progress remediation stops after two laps;
- transition budget cannot be exceeded;
- live target is forbidden.
- recorded scientific and operational evidence is never mutated; progression creates and records
  a superseding package, while gate decisions remain append-only governance attachments.

### Forward scenarios

1. Synthetic breakout package advances to its first legitimate blocker and records exact next
   action without claiming promotion.
2. Synthetic random baseline exits killed and still produces/verifies a receipt.
3. A paper resume with incomplete window exits waiting.
4. A fake reviewer equal to owner is blocked.
5. A request to run through live is forbidden.

### Existing regression suite

- Ruff;
- public repository validator;
- all unit/contract/mutation tests on Python 3.9 and 3.12;
- plugin validator and all seven skill validators;
- clean wheel build and installed-wheel validation;
- default CI remains offline.

## 13. Implementation Order

1. Add this audited plan, machine-readable pipeline policy, and ADR-0009.
2. Implement and test deterministic orchestration state runtime plus the additive `workflow` CLI.
3. Harden all candidate gates to require present, independent owner/reviewer identities.
4. Extend public validation and tests before deleting old skills.
5. Add `run`, `test`, `review`, and `status` skills.
6. Merge `spec` into `research` and harden retained `paper` and `plate`.
7. Implement and test superseding-package and package-root evidence rules.
8. Remove `mise`, `spec`, `screen`, `backtest`, `taste`, `refire`, `simmer`, and `receipts` only
   after replacement contracts exist.
9. Add `.the-pass/` local-state ignore and run-state rules.
10. Update versions, plugin manifest, README, ADRs, command docs, lifecycle docs, and changelog.
11. Run static, state-machine, forward-scenario, plugin, and regression tests.
12. Commit on a protected feature branch, open a PR, require green CI, and merge without weakening
   branch protection.

## 14. Definition of Done

The migration is complete only when:

- `find skills -mindepth 2 -maxdepth 2 -name SKILL.md` returns exactly seven files;
- `/the-pass:run` documents and machine policy represents the full non-live queue;
- all seven specialist contracts invoke the implemented CLI where applicable;
- run state is resumable, bounded, and explicitly non-evidentiary;
- the state behavior is implemented by deterministic runtime code, not only prose;
- review independence and all four gate semantics remain enforced;
- `plate` precedes and supplies the independent `risk_review` gate;
- normal progression never mutates a package after ledger append;
- no removed slash command appears as a current command in README or command docs;
- synthetic pass/block/kill/wait/forbidden scenarios are covered;
- all existing tests and clean-wheel checks pass;
- the final audit reports no open P0/P1 finding;
- GitHub `main` is clean and required CI checks pass.

## 15. Rollback

Rollback is one revert of the consolidation commit. Artifact schemas, Python CLI, ledgers, and
existing experiment packages are unchanged, so rollback does not require data migration. Local
`.the-pass/` state may be deleted safely because it is operational memory; immutable package and
ledger evidence remain authoritative.

## 16. Independent Plan Audit Resolution

A read-only independent review compared this plan with the current CLI, gate evaluator, schemas,
ledger fingerprinting, paper runtime, and accepted ADRs. The first draft had no P0 finding but had
five P1 findings. Implementation was not started until all five were resolved in this document:

| Audit finding | Resolution |
| --- | --- |
| `risk_review` depended on an approval pack produced by the later `plate` stage | Reordered to `paper_gate -> risk_prepare -> plate -> review_risk -> risk_review` |
| Later gates did not enforce reviewer/owner separation in code | Gate evaluator hardening and mandatory owner tests added to scope |
| Progression would mutate fingerprinted packages after receipt append | Superseding-package contract made mandatory for normal progress and remediation |
| Run state was prose without an executable test subject | Deterministic orchestration runtime and additive `workflow` CLI added |
| Paper/risk artifacts were stored outside the package root searched by gates | Exact package-root copy/finalize/append/evaluate contract added |

The audit also identified four P2 gaps: ambiguous default target, incomplete standalone ledger
rules, stale accepted ADRs, and weak top-level CLI checks. Sections 4.1, 10, 11, 11.1, 12, and 13
now resolve them with explicit target semantics, per-skill ledger behavior, ADR-0009, and exact
subcommand contracts.

After these corrections, the plan had no known open P0/P1 design finding. Implementation then
re-ran the audit against the resulting code as described below.

## 17. Implementation Audit and Closure

Implementation completed every ordered item in section 13. The public surface now contains
exactly seven skills, `/the-pass:run` owns the bounded whole-line workflow, and the granular CLI
remains available for automation.

Five independent read-only code-audit rounds were used during implementation. Confirmed findings
were fixed before closure, including forged completion state, stale resume evidence, mutable gate
decisions, audit/evidence binding gaps, duplicate promotion artifacts, handwritten gate decisions,
and hash-consistent forged ledger passes. The final focused audit reported `P0/P1 remaining: no`.

The final trust model is stricter than the original draft:

- gate decisions are create-only and cannot be overwritten or retried under another extension;
- `receipts add-decision` reproduces the decision with the bundled gate policy before append;
- `receipts verify` rebuilds every v2 run and replays every v2 gate decision in ledger order;
- only previously replayed decisions can satisfy paper/risk prerequisites;
- workflow resume verifies the ledger, exact package identity, full artifact set, prerequisite gates,
  stage-specific evidence files, and explicit `evidence_paths` declarations;
- JSON/YAML/YML duplicates of the same core, promotion, audit, or decision artifact are rejected;
- B2 golden ledgers are deterministic and include the quality report in package identity.

Final verification commands, exact results, safety outcome, and residual limitations are recorded
in the linked audit report. The implementation has no open P0/P1 finding and no live order path.

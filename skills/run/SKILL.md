---
name: run
description: "Advance a trading idea or evidence package through the complete non-live The Pass workflow, with durable state, bounded remediation, independent gates, automatic receipts, and honest stops at evidence or safety boundaries."
---

# The Pass Run

Use this as the default command when the user wants a strategy researched and tested end to end.
Run advances every currently executable stage, then stops at the requested gate, a paper waiting
window, a missing independent reviewer, a kill condition, or another hard blocker.

## Inputs

- Idea, source, StrategySpec, package path, or `.the-pass/runs/<run-id>/state.yaml` to resume.
- Target gate: `research_gate`, `paper_gate`, or `risk_review`. A new idea defaults to
  `research_gate`; a passed research package defaults to `paper_gate`; a passed paper package
  defaults to `risk_review`.
- Strategy owner and run owner identifiers.
- Independent reviewer identifier when a review boundary is reachable.
- Optional lower transition or remediation budget. Never exceed policy maxima.

## Read First

- `config/skill-pipeline.v1.yaml`
- `docs/implementation/SLASH_SKILL_CONSOLIDATION_PLAN.md`
- `docs/implementation/ARTIFACT_LIFECYCLE.md`
- `docs/implementation/VALIDATION_AND_SAFETY.md`
- The matching specialist skill: `skills/research/SKILL.md`, `skills/test/SKILL.md`,
  `skills/review/SKILL.md`, `skills/paper/SKILL.md`, `skills/plate/SKILL.md`, or
  `skills/status/SKILL.md`.

## Editable Paths

- `.the-pass/runs/<run-id>/state.yaml` through `the-pass workflow` only.
- New artifacts under `research/`, `experiments/`, and `reports/` allowed by the active
  specialist skill.
- New superseding packages under `experiments/runs/<strategy-id>/<run-id>/`.
- New append-only entries in the selected receipt ledger.

## Blocked Paths

- Any package or artifact already fingerprinted by a receipt.
- Strategy thesis or preregistered search-space changes after results are visible.
- Existing ledger entries, gate decisions, raw paid data, credentials, live configuration, and
  real order code.
- `live_gate` as a target, transition, simulated result, or approval claim.

## Agent Delegation

- Read `docs/plugin/CROSS_RUNTIME.md` before delegating. Prefer a bounded native subagent for a
  single-runtime task; use a validated `agent_task` and explicit `the-pass agents dispatch
  --execute` only when the other provider adds a distinct capability or independent perspective.
- Delegation depth is one. A delegated task cannot invoke another agent, decide a gate, modify the
  workflow ledger, or count as the independent human reviewer.
- Only one external provider dispatch may be active per local user. Use bounded native subagents
  for parallel research/review; do not queue or retry a second external call.
- Classify delegated work as routine, standard, complex, or critical and inspect the resolved
  `economy|balanced|deep` model profile before execution. Never inject a provider model ID into the
  task objective.
- Implementation delegates return an unapplied worktree patch. Review the patch, apply it in the
  caller workspace, and run all required checks before recording progress.

## Procedure

### 1. Start or resume

- Locate the repo root and confirm `the-pass --version`, policy, templates, schemas, and writable
  evidence directories.
- If state exists, run `the-pass workflow status`; verify the shared ledger and referenced package
  before trusting the recorded stage.
- Otherwise mint a stable run ID and create state with `the-pass workflow start`.
- Never use conversation memory as the only stage record.

### 2. Drive the queue

Read the current stage from state and follow its specialist skill exactly:

```text
preflight -> research -> screen -> backtest -> robustness
          -> independent research review -> research_gate
          -> paper prepare -> paper observe -> independent paper review -> paper_gate
          -> risk prepare -> plate -> independent risk review -> risk_review
```

- Do not recursively type another slash command. Read the sibling `SKILL.md`, execute that
  contract, and record its artifacts.
- Use `the-pass workflow advance` after each completed stage. Add evidence paths, package path,
  package ID, next action, and reviewer when required.
- Send one concise progress update at stage boundaries. Do not ask for routine confirmation.
- `complete` means the requested non-live gate has a separately recorded pass decision.
- Resolve every stage boundary with `the-pass agents route`. Follow its provider/model decision
  when delegation is available; do not hard-code a model in the prompt or call every model merely
  because it exists.
- When the user requests guaranteed continuation and authenticated provider CLIs are available,
  prefer `the-pass workflow execute --execute --driver auto`. The supervisor remains the liveness
  authority; a provider's prose response is never a terminal result.
- If supervision is interrupted, run `the-pass workflow status` and resume the same state. Never
  restart from conversation memory or silently abandon an `in_progress` checkpoint.

### 3. Preserve immutable evidence

- Finalize and append every valid run, including blocked and killed runs.
- Once appended, never edit scientific or operational evidence in that package. The only allowed
  later file is a new append-only `gate_decision.*` governance attachment written by the gate
  evaluator. Before adding robustness, review, paper, risk, or approval evidence, create a
  successor with `the-pass workflow supersede` and a new run ID.
- Place every artifact needed by `gate evaluate` in the exact successor package root before
  finalization. Working copies elsewhere are not gate evidence.
- Append the finalized successor, verify the ledger, evaluate the exact gate, append its decision,
  and verify again.
- For a successor, replay every prerequisite gate on that exact package ID in canonical order:
  research before paper; research and paper before risk review.

### 4. Enforce reviewer separation

- Strategy owner, run owner, and reviewer must be present in state and artifacts.
- The reviewer must differ from both owners and work from a read-only review scope.
- Use an independent subagent or reviewer process only when it has a distinct identity. Otherwise
  stop `blocked` and require `/the-pass:review` in an independent context.
- The orchestrator may coordinate review but may not manufacture findings or self-approval.

### 5. Bound remediation

- Enter remediation only for confirmed findings with evidence paths.
- At a target gate, require the exact package's recorded `blocked` or `revise` decision to
  fingerprint that finding. Never remediate an unevaluated target.
- Freeze the thesis, original search space, and all recorded packages.
- Apply one coherent finding-scoped change per lap and create superseding evidence.
- Maximum three remediation laps per gate; stop after two consecutive no-progress laps.
- Every failed attempt consumes budget. Record gate progress only with a ledger-backed successor.
  Gate decisions are never retried automatically.

### 6. Stop honestly

- Return `waiting` for a valid but incomplete paper observation window or external evidence wait.
- Return `blocked` for missing data, owner, independent reviewer, tooling, license, or safety
  evidence. Resume only after resolving the blocker and pass `--resume` on the next transition.
- Return `killed` when the StrategySpec kill condition or gate result says kill.
- A request through live is forbidden; do not create state for it.

## Required Checks

Start and inspect state:

```bash
the-pass workflow start --state <state> --run-id <run-id> --strategy-id <strategy-id> \
  --objective <objective> --target-gate <gate> --strategy-owner <owner> \
  --run-owner <run-owner> --ledger <ledger>
the-pass workflow status --state <state>
```

At each package and gate boundary:

```bash
the-pass validate-package <package>
the-pass receipts add <package> --ledger <ledger>
the-pass receipts verify --ledger <ledger>
the-pass gate evaluate <package> --gate <gate> --reviewer <reviewer> \
  --ledger <ledger> --output <package>/gate_decision.<gate>.yaml
the-pass receipts add-decision <package>/gate_decision.<gate>.yaml --ledger <ledger>
the-pass receipts verify --ledger <ledger>
```

Before extending recorded evidence:

```bash
the-pass workflow supersede <recorded-package> <new-package> \
  --ledger <ledger> --run-id <new-run-id> --created-at <rfc3339>
```

## Outputs

- Durable operational workflow state.
- Specialist artifacts and immutable superseding packages.
- Verified run and gate-decision ledger entries.
- Stage progress, exact blocker or waiting reason, and one final evidence-backed report.
- A supervisor report for mechanically executed runs, including every stage route and state hash.

## Exit States

- `complete`: the requested non-live gate passed and its exact decision is recorded.
- `waiting`: valid external evidence or the declared paper window is incomplete.
- `blocked`: a required artifact, owner, reviewer, provider, tool, or safety condition is missing.
- `killed`: a declared kill condition or gate decision ended the hypothesis.

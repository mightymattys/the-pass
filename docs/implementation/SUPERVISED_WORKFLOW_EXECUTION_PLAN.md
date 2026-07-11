# Supervised Workflow Execution and Model Routing Plan

Status: implemented and verified

Plan date: 2026-07-11

Target version: `0.10.0`

## 1. Objective

Turn `/the-pass:run` from a durable but host-agent-driven procedure into a supervised non-live
workflow. A run must not silently stop after an intermediate agent response, claim success without
the exact gate evidence, or choose a provider/model without a versioned capability decision.

The implementation adds two deterministic control surfaces:

1. `the-pass workflow execute` repeatedly invokes one explicitly trusted local stage driver until
   the workflow reaches `complete`, `waiting`, `blocked`, or `killed`.
2. `the-pass agents route` resolves the role, provider, model profile, model request, effort, and
   rationale for the current workflow stage.

The supervisor controls progress and evidence semantics. It does not invent research evidence,
approve a gate, bypass reviewer independence, apply an external broker patch, unlock live trading,
or retry a failed gate decision.

## 2. Locked Safety Decisions

1. `workflow execute` requires `--execute`; inspection without that flag performs no child process
   execution.
2. The driver is a local argv vector executed with `shell=False`. The command is never parsed by a
   shell and receives a minimal documented `THE_PASS_*` context.
3. The driver is trusted to operate in the selected repository. The supervisor validates its state
   transition and evidence after every invocation; it is not a sandbox for arbitrary commands.
4. One driver invocation may produce at most one workflow transition. Direct state rewrites that
   change immutable identity, skip a stage, falsify counters, or omit gate evidence fail closed.
5. A successful child exit without state progress is an error. A failed child may only be accepted
   when it leaves a valid terminal `blocked`, `waiting`, or `killed` checkpoint.
6. The supervisor never resumes `blocked` or `waiting` automatically. External facts, elapsed paper
   windows, licenses, credentials, or human review must be resolved before a later explicit run.
7. Gate decisions remain non-retryable. Remediation remains bounded by the existing transition,
   lap, and no-progress limits.
8. `live_gate`, venue credentials, authenticated order clients, and real order transport remain
   forbidden.
9. Model routing is policy data, not free-text model selection. Tasks cannot inject provider model
   IDs.
10. Independent review stages must use a provider distinct from the author provider when both
    providers are available. If that separation cannot be established, routing returns `blocked`.

## 3. Supervisor Contract

### Inputs

- existing `.the-pass/runs/<run-id>/state.yaml`;
- repository working directory;
- trusted driver argv after `--driver`;
- optional maximum cycle and per-cycle timeout reductions;
- optional caller and author provider identities for routing.

### Driver environment

Each invocation receives:

- `THE_PASS_WORKFLOW_STATE` as an absolute path;
- `THE_PASS_WORKFLOW_STAGE` and `THE_PASS_WORKFLOW_STATUS`;
- `THE_PASS_WORKFLOW_TARGET_GATE` and `THE_PASS_WORKFLOW_RUN_ID`;
- `THE_PASS_ROUTE_PROVIDER`, `THE_PASS_ROUTE_MODEL`, `THE_PASS_ROUTE_PROFILE`,
  `THE_PASS_ROUTE_EFFORT`, and `THE_PASS_ROUTE_ROLE`;
- `THE_PASS_SUPERVISOR_CYCLE`.

The same driver command can therefore inspect state, execute exactly the current specialist skill,
call `workflow advance`, and exit. It does not need a shell-generated prompt.

### Progress validation

After every child process, the supervisor reloads state and checks:

- immutable run identity and ledger path are unchanged;
- timestamps remain monotonic;
- transition and remediation counters cannot move backwards or jump;
- the destination is allowed by `skill-pipeline.v1.yaml`;
- same-stage changes are limited to valid status/checkpoint updates;
- terminal states contain a reason where required;
- exact-package evidence validates for the resulting stage;
- `complete` still requires the exact package's recorded target gate pass.

### Stop semantics

- exit `0`: exact target gate passed and state is `complete`;
- exit `2`: valid `waiting`, `blocked`, or `killed` result;
- exit `1`: invalid transition, no progress, timeout, driver failure, or exhausted cycle budget;
- exit `3`: forbidden safety operation or attempted live target.

Cycle evidence is written atomically to a supervisor report. It records hashes and bounded metadata,
not raw provider output or credentials. The report must be a distinct file beside workflow state;
auto-driver child environments exclude venue secrets and direct API-key variables.

## 4. Stage-Aware Routing

Routing is stored in `agent-orchestration.v1.yaml` and mirrored in the packaged policy.

| Stage family | Primary provider | Role | Workload |
| --- | --- | --- | --- |
| research and source synthesis | Claude | researcher | complex |
| screen, backtest, data and implementation | Codex | implementer | complex |
| robustness and statistical skepticism | Claude | reviewer | critical |
| independent research/paper/risk review | provider other than author | reviewer | critical |
| paper preparation/observation | Codex | implementer | standard |
| risk evidence and approval packaging | Codex | implementer | complex |
| preflight, gate recording, completion | host/supervisor | coordinator | routine |

Provider preference is a policy default, not an entitlement claim. Routing checks installed/allowed
providers and returns the alternate provider only if its selected catalog entry has all required
capabilities. `agents doctor` continues to distinguish binary availability from authentication and
model access.

The public Codex catalog uses only GPT-5.6 Luna, Terra, and Sol. Claude uses only Sonnet 5, Opus
4.8, and Fable 5. The policy enforces two-to-three current models per provider and rejects older
Codex families. Every route exposes the policy fingerprint and rationale.

## 5. Slash Skill Integration

`/the-pass:run` must:

1. start or resume durable state;
2. inspect `agents route` at every stage boundary;
3. use native subagents for bounded parallel evidence gathering when supported;
4. use cross-provider dispatch only for a distinct capability or independent perspective;
5. use `workflow execute` when a trusted stage driver is available;
6. otherwise keep driving stages in the host session and never call the run complete before the
   deterministic state says `complete`;
7. report an exact terminal state and resume command on interruption.

The command never requires every model to be called. Efficiency means selecting the cheapest model
that satisfies the stage capability and safety floor, escalating only for complex/critical work or
after an evidence-backed failure.

## 6. Tests

Required offline coverage:

- routing for every workflow stage;
- preferred-provider and fallback-provider selection;
- independent-review provider separation;
- public model aliases and profile floors;
- inspect mode performs no execution;
- successful multi-cycle completion through a fixture driver;
- valid blocked/waiting/killed stop;
- successful child with unchanged state fails;
- timeout terminates the child;
- invalid stage skip and counter jump fail;
- exhausted cycle budget fails without claiming completion;
- exact gate evidence remains required for `complete`;
- JSON envelope and exit-code compatibility;
- Python 3.9 and 3.12, default CI offline.

## 7. Documentation and Release

Update README, CLI contract, usage guide, command reference, cross-runtime guide, slash skill,
changelog, plugin manifests, packaged policies, and completion audit. Build and validate wheel and
sdist, run the full offline test matrix, and publish the changes through a protected pull request.

## 8. Definition of Done

- no documented one-command completion claim relies only on agent intent;
- `workflow execute` cannot return success from an intermediate state;
- interrupted runs retain a valid checkpoint and deterministic next action;
- every routed stage identifies role, provider, model, effort, capabilities, and policy hash;
- reviewer separation is enforced rather than suggested;
- all new failure paths have regression tests;
- all repository validation, distribution, and plugin checks pass;
- live execution remains technically locked.

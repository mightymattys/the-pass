# ADR-0009: Consolidated Skill Interface

Status: accepted
Date: 2026-07-10
Owner: automation_engineer

## Context

The initial plugin exposed eleven slash skills. Several represented internal phases rather than
durable user intentions: setup, specification, screen, backtest, review, repair, iteration, and
ledger summary all had separate entry points. That made discovery harder, duplicated safety and
artifact rules, and left end-to-end sequencing in prose.

The useful property of the sous-chef model is not kitchen naming itself. It is one front-door
command that owns a bounded queue while focused commands retain clear responsibilities. Trading
research adds stricter requirements: immutable experiment packages, exact-package gates,
independent reviewers, long-running paper windows, and a technically locked live boundary.

## Decision

The public plugin exposes exactly seven skills:

- `run`: bounded whole-line orchestration to `research_gate`, `paper_gate`, or `risk_review`;
- `research`: source review, hypothesis, and StrategySpec formalization;
- `test`: diagnostic screen and reproducible backtest execution;
- `review`: independent research, paper, and risk review;
- `paper`: isolated replay/paper preparation and observation;
- `plate`: risk and approval-input packaging after paper passage;
- `status`: read-only workflow and ledger summary.

The eleven-skill vocabulary in ADR-0001 and ADR-0006 is historical. Its artifact schemas remain
readable for compatibility, but removed command names are not aliases. Explicit failure is safer
than silently routing old commands to changed semantics.

The orchestration contract is machine-readable in `config/skill-pipeline.v1.yaml` and packaged
with Python. `the_pass.orchestration` validates the stage graph, persists atomic run state,
enforces target and iteration budgets, requires independent reviewers, and creates immutable
successor packages. The additive CLI group is `the-pass workflow start|advance|status|supersede`.

`run` stops at its selected gate. It may return `waiting` for an incomplete paper window,
`blocked` for missing or unsafe evidence, or `killed` for a falsified hypothesis. It never retries
a gate decision and cannot target `live_gate`.

## Alternatives Considered

- Keep eleven commands and add only documentation: rejected because overlap and sequencing would
  remain unenforced.
- Expose only one command: rejected because focused skills are useful for expert intervention,
  testing, and resumability.
- Preserve old aliases indefinitely: rejected because ambiguous aliases conceal changed review
  and immutability semantics.
- Build an autonomous scheduler: rejected because paper windows and operational jobs already fit
  scheduler-neutral CLI execution.

## Consequences

- New users have one default entry point and six comprehensible specialist commands.
- Existing users must use the new names; compatibility applies to evidence, not slash aliases.
- Pipeline changes require policy, tests, skill contracts, and documentation to change together.
- Workflow state is local generated evidence under `.the-pass/` and is not committed.
- Gate evaluators remain the source of promotion truth; the orchestrator cannot self-approve.

## Validation

- Exactly seven `skills/*/SKILL.md` files exist and pass the skill validator.
- Repository and packaged pipeline policies are identical and parse every declared CLI argv.
- Unit tests cover target gates, illegal transitions, budgets, no-progress stops, reviewer
  independence, immutable supersession, JSON envelopes, and the forbidden live target.
- Public README and command documentation contain no removed slash-command references.
- Full offline repository validation, Ruff, unit tests, wheel validation, and safety scans pass.

## Review Trigger

Revisit only when repeated real usage proves that a durable user intention cannot be expressed by
the seven commands, or when a separately accepted live-capability ADR changes the safety boundary.

---
name: spec
description: "Turn a trading idea into a StrategySpec with edge thesis, data needs, execution assumptions, risks, done_when, and kill_when."
---

# The Pass Spec

Use this skill when converting an idea, source claim, or existing strategy into a formal
`StrategySpec`.

## Inputs

- Trading idea, hypothesis, source note, existing strategy description, or code excerpt.
- Intended asset class, venue, instrument set, time horizon, and execution style if known.
- Available data sources and known cost/fill constraints.

## Read First

- `templates/strategy_spec.yaml`
- `schemas/strategy_spec.schema.json`
- `templates/hypothesis.yaml` and `schemas/hypothesis.schema.json` when the input is a
  research hypothesis.
- Relevant `source_note` artifacts in `research/` or the experiment package.
- `docs/implementation/SKILL_CONTRACTS.md`
- `docs/implementation/VALIDATION_AND_SAFETY.md`

## Editable Paths

- `research/hypotheses/`
- `experiments/runs/<strategy-id>/strategy_spec.yaml`
- `examples/**/package/strategy_spec.json` for public-safe fixtures.
- `reports/` only for supporting notes that cite the StrategySpec.

## Blocked Paths

- Data files, execution adapters, credentials, and live configuration.
- Backtest results or verdict reports unless the user explicitly asks to proceed to another skill.

## Procedure

- Classify by edge mechanism, not indicator name.
- Include null/random baselines and kill criteria.
- Require data, cost, fill, latency, and risk assumptions.
- If the idea cannot state a falsifiable edge thesis, keep it in research.
- Write a `StrategySpec` from the template. Do not leave required fields implicit.
- Copy the strategy-level `strategy_spec.yaml` into every
  `experiments/runs/<strategy-id>/<run-id>/` package so package validation is
  self-contained.
- Separate thesis from implementation details: the thesis must be falsifiable before any backtest exists.
- Add `done_when` and `kill_when` that can be checked by `taste`.
- Keep status at `draft` or `research` unless existing artifacts justify a later state.
- Use `research_ready` as the command exit state and `research` as the corresponding
  `StrategySpec.status` value.
- Record all unknowns under assumptions or blockers instead of filling them with optimistic defaults.

## Required Checks

```bash
the-pass validate <path-to-strategy-spec>
```

If the artifact is part of a package, also run:

```bash
the-pass validate-package <package-dir>
```

## Outputs

- A `StrategySpec` based on `templates/strategy_spec.yaml`.
- Open assumptions and blocked fields in the artifact notes or a companion blocker list.
- Gate requirements for research, paper, and live approval.

## Exit States

- `draft`: a structured spec exists but has unresolved research assumptions.
- `research_ready`: the spec is falsifiable, validates, and can be screened or backtested.
- `blocked`: the idea lacks a falsifiable edge, data definition, cost model, or safety boundary.

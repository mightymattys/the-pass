---
name: research
description: "Turn sources or trading ideas into reviewed notes, falsifiable hypotheses, and a validated StrategySpec in source, spec, or automatic mode without treating reading as proof of edge."
---

# The Pass Research

Use this skill for source intake, hypothesis design, StrategySpec creation, or the complete
research-to-spec sequence.

## Inputs

- Topic, URL, DOI, file, source text, trading idea, existing hypothesis, or StrategySpec draft.
- Mode: `source`, `spec`, or `auto`; infer `auto` when the user asks to research an idea end to end.
- Intended asset class, venue, instruments, timing, horizon, and execution style when known.
- Strategy owner identifier and public/private licensing constraints.

## Read First

- `research/sources.yaml` and related source notes.
- `templates/source_note.yaml`
- `templates/hypothesis.yaml`
- `templates/strategy_spec.yaml`
- `schemas/source_note.v2.schema.json`
- `schemas/hypothesis.v2.schema.json`
- `schemas/strategy_spec.v2.schema.json`
- `docs/research/the-pass-plan.md`
- `docs/implementation/VALIDATION_AND_SAFETY.md`

## Editable Paths

- `research/sources/`, `research/backlog/`, `research/hypotheses/`, and `research/specs/`.
- Strategy-level source/spec copies under `experiments/runs/<strategy-id>/`.
- A new, unrecorded package when invoked by `/the-pass:run`.

## Blocked Paths

- Existing run packages, metrics, verdicts, receipts, raw paid data, credentials, and live code.
- Source status or StrategySpec history rewritten to conceal prior assumptions.
- Backtest implementation or result files; use `/the-pass:test` after `research_ready`.

## Procedure

### Source mode

- Prefer primary papers, official technical/provider documentation, and reproducible evidence.
- Record bibliography, URL/DOI, license, checked date, recency, claim, limitations, market
  applicability, required tests, failure modes, and evidence classification.
- Mark inaccessible or license-restricted material blocked; do not count it reviewed.
- Treat investor/operator material as process or risk evidence, not statistical proof.
- Treat OxfordStrat and similar pages as strategy review material that requires independent tests.
- Convert useful claims into falsifiable hypotheses. Reading alone never promotes a strategy.

### Spec mode

- Classify the edge by mechanism, not indicator name.
- Define data and timestamp requirements, signal timing, execution, fills, costs, latency, risk,
  baselines, complete parameter space, validation windows, done conditions, and kill conditions.
- Require strategy owner and all promotion-relevant fields. Unknown values become explicit
  blockers, never optimistic defaults.
- Keep status `draft` until complete and `research` when ready for testing.
- After the first run, material changes require a new StrategySpec version and new package.

### Auto mode

- Complete source review first, then specification only when at least one claim supports a
  falsifiable mechanism.
- If evidence is weak but the idea remains testable, return `blocked` with the exact source or
  design work required. Do not fabricate a complete spec.

## Required Checks

```bash
the-pass validate <source-note> --type source_note
the-pass validate <hypothesis> --type hypothesis
the-pass validate <strategy-spec> --type strategy_spec
```

When the spec enters a package:

```bash
the-pass validate-package <package>
```

## Outputs

- Reviewed source notes and source-registry updates.
- Falsifiable hypothesis artifacts.
- A versioned StrategySpec with owner, baselines, parameter space, done, and kill conditions.
- Explicit blockers and the next legal testing step.

## Exit States

- `research_ready`: reviewed evidence supports a falsifiable, schema-valid StrategySpec.
- `rejected`: the claim is unsupported, non-falsifiable, irrelevant, or fails a declared kill rule.
- `blocked`: required source, license, market definition, data, cost, timing, or owner evidence is missing.

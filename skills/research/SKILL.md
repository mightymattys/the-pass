---
name: research
description: "Convert studies, books, investor notes, vendor docs, or strategy-review pages into structured source notes and falsifiable trading hypotheses."
---

# The Pass Research

Use this skill when the user asks to study a topic, review sources, or turn research into
strategy hypotheses.

## Inputs

- Topic, URL, paper, book excerpt, investor note, vendor documentation, code, or source text.
- Optional market scope and priority.
- Optional target output: source note only, hypothesis list, or StrategySpec candidate.

## Read First

- `templates/source_note.yaml`
- `templates/hypothesis.yaml`
- `schemas/source_note.schema.json`
- `schemas/hypothesis.schema.json`
- Existing related notes in `research/sources/`
- `docs/research/the-pass-plan.md`
- `docs/implementation/SKILL_CONTRACTS.md`

## Editable Paths

- `research/sources/`
- `research/backlog/`
- `research/hypotheses/`
- `experiments/runs/<strategy-id>/source_note.yaml`
- `examples/**/package/source_note.json` for public-safe fixtures.

## Blocked Paths

- Paid or private source dumps.
- Secrets, credentials, account statements, and private fills.
- Promotion verdicts. Reading can create hypotheses, not approval.

## Procedure

- Treat sources as claims, not truth.
- Tag OxfordStrat and similar pages as `strategy-review`, not academic proof.
- Every source note must include claim, evidence, limitations, market applicability,
  required tests, and failure modes.
- Do not recommend promotion from reading alone.
- Prefer primary sources for academic or technical claims. When using secondary strategy-review
  material, label it clearly and require independent tests.
- Extract the smallest falsifiable claim. Avoid bundling unrelated indicators into one hypothesis.
- Record market transfer risk when a source was studied in a different asset class, timeframe, or cost regime.
- Convert only sufficiently precise hypotheses into `StrategySpec` candidates; otherwise leave them in backlog.

## Required Checks

```bash
the-pass validate <path-to-source-note>
the-pass validate <path-to-hypothesis> --type hypothesis
```

## Outputs

- Source notes based on `templates/source_note.yaml`.
- Structured hypotheses based on `templates/hypothesis.yaml` that can become `StrategySpec`
  files.
- Missing evidence and required tests.

## Exit States

- `reviewed`: at least one source note validates and the next required test is explicit.
- `rejected`: the source claim is unusable, non-falsifiable, duplicated, or unsafe.
- `blocked`: the source is unavailable, licensing is unclear, or the claim cannot be summarized without private material.

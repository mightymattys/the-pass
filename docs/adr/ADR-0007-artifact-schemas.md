# ADR-0007: Artifact Schemas

Status: accepted
Date: 2026-07-09
Owner: automation_engineer

## Context

The Pass depends on evidence artifacts. If artifacts are loose Markdown or inconsistent
YAML, gates cannot be automated or independently reviewed.

## Decision

Core artifacts must be schema-backed. The initial repo may ship YAML templates and JSON
schemas first; code validators can follow, but every command should treat schema compliance
as a gate requirement.

Core artifacts:

- Source note.
- StrategySpec.
- Data manifest.
- Run receipt.
- Metrics report.
- Cost waterfall.
- Verdict report.

## Alternatives Considered

- Free-form Markdown only: rejected because it prevents automated gates.
- Database-first schema: rejected for public plugin MVP because portable files are easier to
  inspect and review.

## Consequences

- Contributors can add validators without redesigning artifacts.
- Public examples can be tested mechanically.
- Gate failures can be explained as missing fields instead of subjective judgment.

## Validation

The schema registry and production validator are implemented. Public repository validation now
requires every registered schema to be valid, every packaged schema copy to match, and every
latest-version template to pass the same artifact validator used by the CLI. Templates carry
non-promoting example states and cannot serve as gate evidence without being instantiated and
recorded through the normal package and ledger flow.

## Review Trigger

Revisit when artifact compatibility rules or the schema registry versioning policy changes.

# CLI Contract

The CLI is the scheduler-neutral and engine-neutral interface for validating evidence and
running reference workflows.

## Output Formats

Every command supports `--format text|json`. JSON output always contains:

```json
{
  "ok": true,
  "status": "complete",
  "artifact_paths": [],
  "issues": [],
  "receipt_id": null
}
```

Commands may add fields, but they may not remove or change the meaning of these five keys in a
compatible release. `issues` rows contain at least `path` and `message`. Artifact paths are
absolute for newly written local artifacts unless a documented receipt uses workspace-relative
paths.

## Exit Codes

| Code | Meaning |
| --- | --- |
| `0` | operation succeeded or evaluated gate passed |
| `1` | invalid input, schema failure, missing evidence, or technical failure |
| `2` | valid research result is `blocked`, `revise`, `kill`, `frozen`, or otherwise not promoted |
| `3` | operation is forbidden by the public safety boundary |

Exit code `2` is not a software failure. It means the tool successfully evaluated evidence and
declined promotion.

## Command Groups

- `validate`, `validate-package`: artifact and package validation.
- `data`, `features`: canonical quality and deterministic feature evidence.
- `screen`, `backtest`: preregistered diagnostics and deterministic reference simulation.
- `robustness`, `risk`: statistical and policy-independent risk evidence.
- `gate`: artifact-backed candidate gate evaluation.
- `paper`: isolated virtual paper execution.
- `automation`, `incident`: scheduler-neutral jobs and fail-closed incidents.
- `report`, `dashboard`: static read-only evidence bundles.
- `receipts`: append-only run and gate-decision ledger operations.
- `workflow`: validated local run state, evidence resume checks, package fingerprinting, and
  immutable successor creation.

## Compatibility

- Existing required JSON keys and exit-code meanings are stable within a major version.
- New optional fields and new commands are additive minor-version changes.
- A breaking field or semantic change requires a new major version and migration note.
- Text output is for humans and is not a stable parsing interface.
- Candidate gate IDs remain `research_gate`, `paper_gate`, `risk_review`, and `live_gate`.
- Framework milestone passes never imply that a candidate gate passed.

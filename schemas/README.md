# Schemas

These JSON Schemas define the first public contract for The Pass artifacts. They are
intentionally conservative: a file can contain more detail than the schema requires, but
gate-critical fields should be present and typed.

Core run artifacts:

- `source_note.schema.json`
- `hypothesis.schema.json`
- `adapter.schema.json`
- `strategy_spec.schema.json`
- `data_manifest.schema.json`
- `run_receipt.schema.json`
- `metrics_report.schema.json`
- `cost_waterfall.schema.json`
- `verdict_report.schema.json`

Slash-workflow artifacts:

- `screen_report.schema.json`
- `findings.schema.json`
- `refire_ticket.schema.json`
- `simmer_laps.schema.json`
- `paper_plan.schema.json`
- `observation_manifest.schema.json`
- `divergence_report.schema.json`
- `approval_pack.schema.json`
- `receipt_summary.schema.json`

The implemented `the-pass validate` and `the-pass validate-package` commands accept YAML or
JSON input, parse it into structured data, and validate against these schemas plus semantic
cross-artifact checks before a gate can pass.

# Paper, Automation, And Reporting

The paper broker is a separate virtual process. It reads canonical JSONL and a hashed risk
policy, emits only simulated evidence, and has no adapter, credential, account, or external
transaction dependency.

Automations are CLI jobs intended for cron, GitHub Actions, or an external orchestrator.
There is no internal scheduler. Retry is allowed only for idempotent fetch/report jobs.

The dashboard is a static HTML bundle generated from artifacts and DuckDB aggregation. It
cannot mutate gates, policies, limits, StrategySpec, or approval state.

P4 capability is implemented, but its gate remains blocked until a real candidate completes
the asset-specific paper window.

# Paper, Automation, And Reporting

The compatibility paper broker is a one-shot virtual process. The supported custom-strategy
observer adds immutable batches, replay-based state reconstruction, configuration hashes,
historical intent/fill prefix verification, append-only invocation hashes, and a sticky freeze on
data, risk, overlap, tamper, or configuration breaches. It emits only simulated evidence and has no
adapter, credential, account, or external transaction dependency. Offline replay never proves a
real elapsed paper window.

Automations are CLI jobs intended for cron, GitHub Actions, or an external orchestrator.
There is no internal scheduler. Retry is allowed only for idempotent fetch/report jobs. Each named
job invokes a domain handler and reads its declared evidence; a generic receipt cannot by itself
produce `complete`.

The dashboard is a static HTML bundle generated from artifacts and DuckDB aggregation. It
cannot mutate gates, policies, limits, StrategySpec, or approval state.

P4 capability is implemented, but its gate remains blocked until a real candidate completes
the asset-specific paper window.

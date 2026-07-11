# The Pass v0.10.0

Status: source implementation complete; release tag pending protected review.

`v0.10.0` adds supervised end-to-end execution and stage-aware Codex/Claude model routing.

## Highlights

- `the-pass workflow execute` repeatedly invokes one trusted stage driver and validates every
  durable checkpoint.
- `--driver auto` selects the provider, model profile, model request, and reasoning effort from a
  versioned stage policy.
- `the-pass agents route` exposes that decision without executing or charging a model call.
- Codex is preferred for implementation, data, backtests, paper, and risk packaging; Claude is
  preferred for research synthesis and adversarial/statistical review.
- Independent review routes fail closed unless the author provider is known and a different
  provider is available.
- Preflight and all gate recording remain deterministic and outside model authority.
- Routing contains no Codex model older than GPT-5.6 and keeps exactly three reviewed current
  models per provider.
- Timeout, no progress, illegal state jumps, invalid evidence, and budget exhaustion cannot produce
  a false `complete` result.

## Upgrade

Until the `v0.10.0` release is tagged, use a reviewed source checkout. The latest published wheel
remains `v0.9.1`.

After release, update both the CLI and plugin so the packaged routing policies match the source
manifest version. Authenticate both local provider CLIs before using the default two-provider auto
route.

See the [usage guide](USAGE_GUIDE.md),
[execution plan](../implementation/SUPERVISED_WORKFLOW_EXECUTION_PLAN.md), and
[audit](../../reports/SUPERVISED_WORKFLOW_AUDIT_2026-07-11.md).

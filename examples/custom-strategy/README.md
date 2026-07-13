# Custom Strategy Offline Smoke

This example proves the supported user-strategy path without network access. It is a
two-bar framework smoke, not market evidence and not a promotion candidate.

```bash
WORK="$(mktemp -d)"

uv run the-pass data ingest \
  --provider futures \
  --archive-root tests/fixtures/futures \
  --request examples/custom-strategy/fetch-request.json \
  --output "$WORK/data" \
  --format json

uv run the-pass backtest run \
  --descriptor examples/custom-strategy/descriptor.json \
  --strategy-spec examples/custom-strategy/strategy-spec.json \
  --events "$WORK/data/canonical-events.jsonl" \
  --data-manifest "$WORK/data/data-manifest.json" \
  --quality-report "$WORK/data/quality-report.json" \
  --execution examples/custom-strategy/execution.json \
  --workspace-root examples/custom-strategy \
  --output "$WORK/package" \
  --format json

uv run the-pass validate-package "$WORK/package" --format json
```

`backtest run` executes two fresh workers and refuses to package differing results.
The output verdict remains `blocked` until real data, robustness, risk, and independent
review evidence exist.

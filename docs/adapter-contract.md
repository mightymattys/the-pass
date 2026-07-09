# Asset-Class Adapter Contract

The Pass core is market-agnostic. Asset-class adapters are responsible for translating
market-specific data, costs, execution assumptions, and settlement rules into common
artifacts.

## Required Adapter Outputs

- `adapter.yaml` describing mode, asset class, providers, engine, and safety boundary.
- Provider review fields covering license, redistribution, authentication, retention,
  deterministic replay, and limitations.
- Source notes for provider and market-structure assumptions.
- StrategySpec with asset class, venue, instrument universe, horizon, and edge thesis.
- Data manifest with provider, license note, schema, time coverage, fingerprints, and gaps.
- Metrics report with gross and net results.
- Cost waterfall with fees, spread, slippage, funding/borrow/roll/settlement costs where
  relevant.
- Verdict report with gate status and blockers.

## Required Adapter Decisions

- Provider and licensing ADR.
- Instrument metadata policy.
- Timestamp policy: event time, receive time, decision time, execution time.
- Cost model policy.
- Fill model policy.
- Risk and sizing policy.
- Settlement or corporate-action policy where relevant.

## Adapter Modes

| Mode | Meaning | Promotion |
| --- | --- | --- |
| diagnostic | Useful for exploration only. | Cannot promote to paper |
| research | Can support backtest research. | Can enter `taste` |
| paper | Can support paper/replay observation. | Can recommend risk review |
| live-capable | Has separate live ADR, dry-run, risk, and credential boundary. | Human approval only |

## `adapter.yaml`

Minimum shape:

```yaml
id: synthetic-breakout
name: Synthetic Breakout Adapter
mode: diagnostic
asset_classes: [synthetic]
owner: ""

providers:
  - id: synthetic-fixture
    type: synthetic
    license: public-safe
    url: ""
    fields: [timestamp, open, high, low, close, volume]
    limitations: []

provider_review:
  license: public-safe synthetic fixture
  redistribution: fixture can be redistributed with the repository
  authentication: none
  retention: tracked fixture data only
  deterministic_replay: true
  limitations: []

engine:
  name: none
  role: fixture-only
  limitations: []

policies:
  timestamp: ""
  cost_model: ""
  fill_model: ""
  risk_model: ""
  settlement: ""

safety:
  live_trading_enabled: false
  real_order_path_available: false
  credentials_required: false
```

Promotion constraints:

- `diagnostic` adapters cannot support paper promotion.
- `research` adapters need provider/license review and deterministic replay.
- `paper` adapters need paper/replay observation and divergence policy.
- `live-capable` adapters need a separate live ADR and human approval.

## Adapter Gate Checklist

- Data provider license is documented.
- Redistribution rights are explicit before data is committed or published.
- Authentication and credential needs are explicit.
- Retention and replay policy are explicit.
- Timestamp policy separates event time and receive time where relevant.
- Instrument metadata is explicit.
- Cost and fill assumptions are explicit.
- Missing fields and limitations are listed.
- Safety flags are false for public examples.
- Adapter mode matches the evidence quality.

## Examples

- Concrete public-data descriptor: [crypto Binance spot klines](adapters/crypto-binance-spot-klines.md).
- Crypto perp adapter: funding, mark/index price, liquidation events, book depth, venue
  outages.
- Futures adapter: contract metadata, roll policy, sessions, tick value, exchange fees.
- Prediction-market adapter: market semantics, resolution source, fee endpoint, depth,
  settlement reconciliation.
- Equities/options adapter: corporate actions, borrow, expiries, assignment/exercise,
  exchange/broker fees.

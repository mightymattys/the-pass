# Crypto Binance Spot Klines Diagnostic Adapter

This is the first concrete public-data adapter descriptor for The Pass.

It is diagnostic only. It does not download data, place orders, require credentials, or
claim a trading edge. It documents how a Binance spot kline data source would enter The
Pass through the generic adapter contract.

## Primary Sources

- [Binance Spot market data endpoints](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints)
- [Binance market-data-only URLs](https://developers.binance.com/docs/binance-spot-api-docs/faqs/market_data_only)
- [Binance public data collection](https://data.binance.vision/)
- [Binance public data notes](https://github.com/binance/binance-public-data)

## Boundary

- Mode: `diagnostic`.
- Provider: Binance public spot market data.
- Endpoint family: spot klines/candlesticks.
- Authentication: none for market-data-only public endpoints.
- Repository data policy: no downloaded Binance data is committed.
- Replay policy: live endpoint data is not deterministic evidence; research promotion needs
  archived snapshots or licensed replayable data.

## Required Before Research Promotion

- Provider terms and redistribution rights reviewed for the intended use.
- Raw responses stored immutably with receive timestamps.
- Endpoint rate limits, outages, truncation, and clock skew recorded.
- Cost model supplied from venue fees, spread, slippage, and missed-fill assumptions.
- Fill model upgraded beyond kline bars if execution quality matters.
- Cross-source sample check against another provider or archived venue data.

## Why Diagnostic Only

Klines can be useful for smoke-testing data manifests and coarse screens, but they do not
prove queue position, executable spreads, order book depth, fee tier, latency, or actual
fills. The adapter therefore cannot produce a paper candidate verdict by itself.

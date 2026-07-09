# Adapter Examples

These adapters prove the core The Pass validator can describe multiple markets without
hardcoding market logic.

They are adapter descriptors, not trading systems. None of them can place orders, hold
credentials, or promote a strategy by themselves.

## Files

- `dummy-diagnostic.yaml`: minimum public-safe dummy adapter.
- `crypto-binance-spot-klines.yaml`: first concrete public-market-data diagnostic adapter.
- `generic-futures-contract.yaml`: futures contract descriptor showing roll/session/cost fields.
- `generic-prediction-market.yaml`: prediction-market descriptor showing settlement and resolution fields.

The Binance descriptor documents public market-data boundaries in
[../../docs/adapters/crypto-binance-spot-klines.md](../../docs/adapters/crypto-binance-spot-klines.md).

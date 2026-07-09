# Adapters

Adapters describe market-specific data, costs, fill assumptions, settlement rules, and
safety boundaries. They do not live inside the core validator as special cases.

The core only enforces the common contract:

- provider identity, fields, licensing, authentication, retention, and limitations,
- timestamp, cost, fill, risk, and settlement policies,
- mode-specific safety checks,
- no live trading path unless a separate live readiness pack exists.

Example descriptors live in [../../examples/adapters/](../../examples/adapters/).

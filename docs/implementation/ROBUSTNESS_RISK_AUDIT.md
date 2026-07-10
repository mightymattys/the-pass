# Robustness, Risk, And Audit

V3 operates on the complete preregistered variant matrix. It does not accept a selected
winner without the number and results of all trials.

## Statistical Controls

- Anchored and rolling walk-forward
- Purged split and embargo
- CSCV/PBO
- PSR and DSR with non-normal return correction
- Deterministic block bootstrap and regime splits
- White Reality Check and SPA
- Neighbor sensitivity and IS/OOS degradation

## Risk Boundary

`config/risk-policies.v1.yaml` contains the exact asset-specific thresholds from the main
plan. A generated `RiskReport` stores the policy hash. Strategies receive a frozen risk
policy through the runner and cannot mutate sizing or limits.

## Independent Audit

The audit runner creates a clean temporary directory, calls the public backtest and receipt
commands, then compares artifact fingerprints. Stats and execution reviewers can each block
promotion. Audit findings record severity, evidence, status, recommendation, and promotion
impact.

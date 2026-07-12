# Repository Hardening Audit

Audit date: 2026-07-10

Scope: full public repository on `codex/repository-hardening-audit`

Result: pass for the implemented framework; candidate paper/live states remain blocked

## Audit Question

The audit tested whether The Pass actually enforces its stated purpose: transforming trading
research into reproducible, cost-aware, independently reviewed evidence without silently crossing
data, credential, promotion, or live-execution boundaries. File presence and schema validity alone
were not treated as proof.

## Corrected Findings

| Severity | Finding | Resolution |
| --- | --- | --- |
| P1 | Paper workers inherited the parent environment while claiming credentials were absent. | Paper subprocesses now receive a minimal environment allowlist and inspect their real environment. Future-received events freeze observation. |
| P1 | Intraday metrics used a hard-coded 252-period annualization and gross path metrics reused net equity returns. | Metrics now record an asset-calendar/median-interval policy and reconstruct a distinct timestamped gross equity curve. Promotion requires explicit annualization evidence. |
| P1 | Reviewer independence was case- and whitespace-sensitive. | Owner/reviewer identities are normalized for comparison and gate CLI input rejects surrounding whitespace. |
| P1 | V3 could pass while its risk report referenced a stale package ID. | V3 validation now recomputes the current package ID and checks every reproduction fingerprint against current files. |
| P2 | Conflicting events with one market key escaped duplicate detection when their raw hashes differed. | Duplicate identity now follows source, venue, instrument, event type, event time, and provider sequence; coverage truncation is checked per instrument. |
| P2 | Risk checks allowed intents without a price and treated lifetime loss as daily loss. | Missing reference prices fail closed; portfolios track UTC-day starting equity and books provide midpoint marks where valid. |
| P2 | A diagnostic midpoint fill could consume a book from another instrument. | Fill models bind instrument and event type and reject invalid price, quantity, fee, and cost values. |
| P2 | Concurrent ledger writers could build entries from the same previous hash. | POSIX append transactions now lock the ledger across verification/build/write and use a durable `fsync` append. |
| P2 | Multi-file automation output could become partially visible. | Worker output is prevalidated, rejects symlinks, and is exposed by one atomic directory rename. |
| P2 | Codex routing used model labels that were not bound to a reviewed current-model allowlist. | Superseded by the `0.10.0` policy: only GPT-5.6 Luna/Terra/Sol are accepted, with a mechanical GPT-5.6 floor and two-to-three-model limit; doctor still does not claim entitlement. |

No unresolved P0 or P1 finding remains in the audited framework state.

## Verification

- `uv lock --check`: pass.
- `uv run ruff check .`: pass.
- `uv run python scripts/validate_public_repo.py`: pass across roadmap, research, D1, B2,
  V3, P4, schemas, templates, plugins, and safety scans.
- Python 3.12: 181 tests passed.
- Python 3.9 isolated environment: 181 tests passed.
- B2: six packages, eleven preregistered variants, deterministic clean replay.
- V3: current package binding, robustness, risk, independent audits, and clean reproduction pass;
  the synthetic candidate remains blocked.
- P4: runtime/automation/reporting capability passes; the synthetic observation remains blocked.
- Wheel and sdist build; clean installed-wheel validation passes.
- Claude strict manifest validation and isolated local source installation for both Codex and
  Claude pass with the plugin enabled at version `0.9.1`.
- `pip-audit`: no known third-party dependency vulnerability; the local unpublished package is
  correctly skipped as unavailable on PyPI.
- Explicit public network smoke: Binance BTCUSDT/ETHUSDT, Polymarket discovery/book/dynamic fee,
  and the futures fixture pass with no credentials, authenticated channels, provider writes, or
  real order path.

## Residual Boundaries

These are deliberate operating boundaries, not hidden completion claims:

- No authenticated Codex or Claude model dispatch was made during this audit. Binary presence,
  routing argv, isolation, and fixture dispatch are tested; model entitlement requires an explicit
  paid `agents dispatch --execute` request.
- Futures promotion still requires a user-supplied licensed archive. Public fixtures prove only
  the contract and replay path.
- No real strategy has completed its required paper observation window. Framework capability is
  complete; candidate promotion is not implied.
- Live order transport, authenticated venue clients, and credential loaders remain absent and
  technically locked.
- Public provider terms, schemas, and endpoints can drift; scheduled read-only smoke and
  maintenance audits remain ongoing controls.

## Conclusion

The repository now addresses the core testing problem coherently: it fails closed on unavailable
data and prices, separates gross and net evidence, binds reviews and gates to exact packages,
serializes immutable receipts, isolates paper and agent processes, and retains negative outcomes.
It is a robust research/testing framework, not evidence that any bundled strategy is profitable or
ready for live capital.

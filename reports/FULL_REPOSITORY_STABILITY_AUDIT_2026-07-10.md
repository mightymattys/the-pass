# Full Repository Stability Audit

Audit date: 2026-07-10

Source version: `0.9.0`

Audited baseline: `b8012e1`

Verdict: pass after remediation; no open P0 or P1 framework finding

## Scope

This audit covers the complete public source tree: package and plugin metadata, schemas,
templates, CLI groups, data and adapter contracts, deterministic research engines, statistics,
risk, paper isolation, automation, reporting, slash skills, Codex/Claude orchestration,
distribution contents, documentation, and the locked live boundary. It evaluates whether the
repository can test strategies safely and reproducibly. It does not evaluate or approve a real
trading strategy.

## Capability Inventory

| Surface | Verified capability |
| --- | --- |
| Research | 50 structured source notes, 31 reviewed notes, 5 OxfordStrat hypotheses, and 5 StrategySpecs |
| Artifacts | 37 registered types, 56 JSON Schema files including compatibility and provider schemas, and 37 latest-version templates |
| Data | Canonical events, instrument registry, quality checks, immutable Parquet commits, deterministic features, and DuckDB query/report support |
| Adapters | Public read-only Binance and Polymarket clients plus a Databento-compatible futures fixture/replay lane |
| Testing | NumPy/pandas screening, deterministic event replay, costs, fills, accounting, baselines, and complete experiment packages |
| Validation | Walk-forward, purged/embargo splits, PBO, PSR/DSR, bootstrap, Reality Check/SPA, sensitivity, regimes, stress, and risk reports |
| Governance | Separate immutable run and gate-decision ledger entries with exact package/path/evidence binding and independent review |
| Paper and operations | Isolated virtual paper worker, fail-closed observers, divergence evidence, nine scheduler-neutral jobs, incidents, and static dashboards |
| Agent interface | Seven shared Codex/Claude skills, bounded workflow state machine, four Claude native agents, and explicit cross-provider dispatch |
| Safety | No authenticated trading client, credential loader, real order transport, or public live approval path |

## Verification Results

The following checks passed against the audited source tree:

| Check | Result |
| --- | --- |
| Lock consistency | `uv lock --check` passed |
| Lint | `uv run ruff check .` passed |
| Public repository validator | Passed, including schema copies, plugin policies, examples, links, secret/live-path scans, and all 37 templates |
| Offline test suite | 172 tests passed |
| Research corpus | 50 structured, 31 reviewed, 5 OxfordStrat hypotheses, 5 StrategySpecs |
| Codex/Claude availability | Codex CLI `0.144.0-alpha.4` and Claude Code `2.1.153` detected by `agents doctor` |
| Public adapter smoke | Binance BTCUSDT/ETHUSDT, Polymarket market/book/fee data, and futures fixture replay passed read-only |
| Deterministic 10k benchmark | All stages completed; peak Python-managed memory was approximately 53.9 MB |
| CLI surface | Every documented command group returned help successfully |

The 10,000-event benchmark measured approximately 0.368 s for event generation, 0.004 s for
sorting, 0.245 s for quality checks, 0.209 s for feature construction, 0.272 s for replay,
1.359 s for immutable Parquet work, 0.142 s for dashboard generation, and 0.008 s for ledger
verification. These measurements are framework performance evidence, not strategy performance.

## Finding And Remediation

### P1: templates were advertised as valid but most were only blank skeletons

The README described `templates/` as valid starting points, while production artifact validation
accepted only 7 of 37 files. The public validation script checked YAML syntax and schema version,
but did not run the artifact validator. A user could therefore begin with an invalid template and
discover missing values only later in a workflow.

Resolution:

- all 37 templates now pass their registered latest-version schema and semantic validator;
- example timestamps, hashes, identifiers, chronology, metrics, costs, and required evidence
  shapes are internally consistent;
- starter states remain deliberately `draft`, `diagnostic`, `blocked`, or failed, so a template
  cannot imply candidate promotion;
- `scripts/validate_public_repo.py` now validates every template through
  `validate_artifact(...)`, making this a permanent release invariant;
- README, installation guidance, ADR-0007, completion evidence, and the changelog now describe the
  implemented behavior accurately.

No other P0 or P1 finding remained after the full pass.

## Stability And Efficiency Assessment

The implementation is appropriately layered for a public testing framework. The base install
keeps validation lightweight, research/data dependencies are optional extras, default CI remains
offline, network checks are explicit, scheduling stays external, and reports are static. The
deterministic engine is intentionally small enough to audit rather than attempting to become a
venue execution platform.

The current design is robust for research, screening, backtesting, audit, and isolated paper
observation. It is intentionally incomplete for live trading. That boundary is a safety property,
not a framework defect.

## Residual Boundaries

- A real candidate still needs licensed or sufficiently archived market data, preregistration,
  independent review, and its full paper observation window.
- Futures remain diagnostic without a user-supplied licensed archive.
- Public network APIs and provider CLI behavior can drift; scheduled/manual smoke checks remain
  necessary even though default CI is offline.
- Cross-provider model execution requires locally installed, authenticated CLIs and is always
  explicit; model output is evidence input, never gate authority.
- Version `0.9.0` is the current source/plugin version. The release badge and GitHub release page
  remain authoritative for what has been tagged and published.

## Conclusion

The source tree is internally consistent, reproducible, public-safe, and usable as the intended
strategy-testing repository. Framework gates are complete; candidate and live gates remain bound
to real evidence and explicit safety decisions.

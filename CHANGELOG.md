# Changelog

All notable changes to The Pass are documented here. The project follows Semantic Versioning
and the Keep a Changelog structure.

## [Unreleased]

### Added

- A Claude Code plugin manifest and four bounded native agents backed by the same seven public
  workflow skills as Codex.
- Provider-neutral `agent_task`, `agent_result`, and `agent_run` artifacts plus `the-pass agents`
  doctor, inspect, and explicit dispatch commands.
- Depth-one, no-retry cross-provider orchestration with read-only delegation, isolated worktree
  patches, protected authority paths, create-only receipts, and no automatic patch application.
- Capability-aware `economy`, `balanced`, and `deep` model routing with deterministic workload and
  safety floors, inspect-time previews, and receipt-level model/effort evidence.

### Changed

- Hardened delegated provider processes by excluding user/project MCP, connector, plugin, hook,
  rule, and native multi-agent configuration.
- Serialized external dispatches, terminated residual provider process groups, rechecked detached
  worktree symlinks, protected broker output paths, and made patch fingerprints semantically
  verifiable.
- Converted all 37 artifact templates into schema-valid, deliberately non-promoting starters and
  made their production-validator checks mandatory in public repository validation.
- Refreshed installation, capability, completion, and audit documentation for the `0.9.0` source
  tree.

## [0.8.0] - 2026-07-10

### Added

- `/the-pass:run`, a bounded and resumable whole-line orchestrator from research through the
  selected `research_gate`, `paper_gate`, or `risk_review` target.
- A machine-readable seven-skill pipeline policy and additive `the-pass workflow` state CLI.
- Immutable successor-package support and regression coverage for transition budgets,
  no-progress stops, target gates, reviewer independence, and the locked live boundary.

### Changed

- Consolidated eleven overlapping slash skills into seven public commands: `run`, `research`,
  `test`, `review`, `paper`, `plate`, and `status`.
- Promotion gates now require the reviewer to differ from both the StrategySpec owner and run
  owner.
- Failed target gates can now stop, resume, or enter bounded remediation without bypassing
  completion checks, passed targets complete at the transition-budget boundary, and successor
  packages require ledger-backed source provenance.
- Remediation accounting is derived from workflow transitions, defaults to no gate progress, and
  requires concrete finding evidence on entry. Target-gate remediation additionally requires a
  recorded exact-package non-pass decision, while progress requires a recorded successor.
- Successor lineage is enforced by every ledger append and semantic replay, including predecessor
  package, strategy, run ID, and artifact fingerprint checks.
- Only exact-path v2 runs and decisions are authoritative; semantic replay enforces run-before-gate
  ordering, and exhausted workflow budgets cannot be resumed.

## [0.7.1] - 2026-07-10

### Fixed

- Release checksums now use asset basenames and verify after downloading assets from GitHub.
- The release workflow resolves audit and release-note files from the pushed tag version.

## [0.7.0] - 2026-07-10

### Added

- Process-isolated automation execution with enforced deadlines, staged output promotion,
  retry controls, incident artifacts, and freeze evidence.
- Installed-wheel validation outside the repository checkout.
- Machine-tested separation between framework capability and candidate promotion states.
- Release, compatibility, installation, maintenance, and benchmark documentation.

### Changed

- CI now validates the lock file, runs Ruff, builds distributions, and tests the installed
  wheel on Python 3.9 and 3.12.

## [0.6.0] - 2026-07-10

### Added

- Canonical data and adapter contracts for Binance Spot, futures fixtures, and Polymarket.
- Deterministic screen, baseline backtest, robustness, risk, paper, automation, and static
  reporting capabilities.
- Versioned v2 artifacts, ledger gate decisions, research corpus, and locked live boundary.

## [0.1.0] - 2026-07-09

### Added

- Initial public plugin, slash skills, artifact schemas, validators, and synthetic examples.

[Unreleased]: https://github.com/matk0shub/the-pass/compare/v0.8.0...HEAD
[0.8.0]: https://github.com/matk0shub/the-pass/compare/v0.7.1...v0.8.0
[0.7.1]: https://github.com/matk0shub/the-pass/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/matk0shub/the-pass/compare/f9fb5e0...v0.7.0

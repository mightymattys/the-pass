# Changelog

All notable changes to The Pass are documented here. The project follows Semantic Versioning
and the Keep a Changelog structure.

## [Unreleased]

## [0.13.0] - 2026-07-15

### Added

- Added full committed-ingest bundle validation and dataset-receipt v2 chunk fingerprints covering
  requests, raw responses, canonical events, quality, manifests, receipts, and commit markers.
- Added explicit `trusted_local` and `hardened` strategy runtime modes, fingerprinted external
  sandbox-launcher evidence, and reproduction-spec v2 isolation metadata.
- Added Ed25519 reviewer keys, public reviewer-key registries, reviewer-attestation v2, and
  secret-free historical gate and ledger verification.

### Changed

- Automated workflow stages now execute in a detached worktree and apply only a validated,
  scope-limited patch after confirming the caller snapshot is unchanged.
- Automated independent review stops at a signed-evidence waiting checkpoint instead of minting
  approval from a supervisor-wide shared secret.
- Public documentation now distinguishes trusted code containment, OS-enforced isolation,
  cryptographic integrity, and organizational reviewer identity.

### Fixed

- Dataset resume no longer trusts changed raw, request, or auxiliary chunk evidence that happens to
  preserve the canonical-event fingerprint.
- Failed or malformed auto-agent cycles can no longer leave workspace mutations behind before state
  validation.
- Reviewer evidence remains verifiable after signing-key removal or rotation; legacy HMAC evidence
  remains readable but cannot authorize a new gate pass.

## [0.12.0] - 2026-07-15

### Added

- Added a beginner-first guide that explains whether users need historical data, how supported
  data acquisition and user archives differ, how to run the offline smoke, and how to interpret
  terminal workflow states.
- Added deterministic `data plan`/`data build`, clean custom-package `audit reproduce`, and signed
  manual or supervisor-created reviewer attestations.
- Added schemas and regression coverage for dataset plans/receipts, reproduction specifications,
  reviewer provenance, state transaction failures, and tampered committed datasets.

### Changed

- Reordered the README around a three-step install-and-run path and expanded the Usage Guide with
  explicit entry paths for an idea, a market archive, trusted strategy code, or an external
  backtest package. Public documentation now assigns beginner, installation, and advanced topics
  to separate canonical guides instead of repeating complete setup and smoke sections.
- Workflow drivers now receive proposal state and only the supervisor can atomically commit a
  validated transition. External dispatch serialization is scoped by workspace.
- New research, paper, and risk gate passes require a matching HMAC-SHA256 reviewer attestation;
  unattested historical evidence remains readable and receives a blocked result.

### Fixed

- Committed dataset resume now revalidates aggregate events, quality, manifest, receipt, and every
  chunk instead of trusting only the final marker.
- Clean reproduction rejects undeclared workspace files, symlinks, unsafe paths, changed inputs,
  unknown runners, and semantic output mismatches.

## [0.11.0] - 2026-07-13

### Added

- Added a trusted local strategy runtime with strict descriptors, explicit execution profiles,
  credential-free subprocesses, deterministic double execution, bounded output, and generic
  diagnostic package generation from real StrategySpec/DataManifest/QualityReport inputs.
- Added `data ingest` for atomic read-only adapter bundles, `robustness sweep` for complete
  preregistered strategy matrices, and resumable `paper observe` with immutable batches and replay
  prefix checks.
- Added conservative research-evidence scope reports and fail-closed model-catalog freshness checks.
- Added an executable offline custom-strategy example and end-to-end regression coverage.
- Extended the explicit public network smoke to build temporary Binance backtest and Polymarket
  scanner packages while retaining metadata fingerprints only.

### Changed

- Named automation jobs now execute domain-specific handlers and cannot report `complete` without
  reading their declared evidence.
- Simulator input validation now rejects malformed intent identifiers/times, out-of-universe
  instruments, excessive intent counts, non-intent results, and canonical-event mutation.
- Historical Binance bars now use provider close time as conservative decision availability while
  preserving HTTP observation time in transport evidence.

### Fixed

- Generic run packages now preserve user data/specification claims instead of hard-coding synthetic
  provider, date, command, and execution metadata.
- Futures fixture reads now respect instrument/time/limit windows and use content-derived ingest IDs.

## [0.10.0] - 2026-07-12

### Added

- Added `the-pass workflow execute`, a bounded liveness supervisor with atomic cycle reports,
  timeout/output limits, one-transition enforcement, resume-safe checkpoints, and explicit
  inspect-versus-execute behavior.
- Added `the-pass agents route` and versioned stage-aware routing across Codex and Claude model
  profiles, including preferred specialists, capability floors, fallback selection, and mandatory
  author/reviewer provider separation.
- Added the explicit `--driver auto` mode, which executes agent stages with locally authenticated
  provider CLIs while keeping preflight and gate recording deterministic.

### Changed

- Raised the Codex routing floor to GPT-5.6 and limited each provider to three reviewed current
  models: Luna/Terra/Sol for Codex and Sonnet 5/Opus 4.8/Fable 5 for Claude.
- Replaced preview-style Codex routing labels with public capability-tier aliases and preserved
  explicit entitlement uncertainty in agent diagnostics.
- Added asset-calendar annualization and distinct timestamped gross/net equity metrics.
- Made ledger appends durable and serialized, automation output commits atomic, and V3
  reproduction/package binding authoritative.

### Fixed

- Closed case/whitespace reviewer-independence bypasses, cross-instrument midpoint fills,
  conflicting-event duplicate gaps, missing-price risk bypasses, and lifetime-as-daily loss checks.
- Removed credential inheritance from paper workers, blocked future-received paper events, and
  expanded nested secret-key detection for config and automation artifacts.

## [0.9.1] - 2026-07-10

### Added

- A repository-backed Codex marketplace catalog with a validated remote installation path.
- A complete usage guide covering CLI setup, both plugins, first smoke, guided runs, direct
  workflow operation, external engines, paper observation, and agent delegation.

### Fixed

- Claude marketplace installation now clones the public repository over HTTPS instead of
  requiring a configured GitHub SSH key.
- Package, plugin, marketplace, and orchestration-policy versions are validated from one source
  version during public repository checks.

## [0.9.0] - 2026-07-10

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

[Unreleased]: https://github.com/mightymattys/the-pass/compare/v0.13.0...HEAD
[0.13.0]: https://github.com/mightymattys/the-pass/compare/v0.12.0...v0.13.0
[0.12.0]: https://github.com/mightymattys/the-pass/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/mightymattys/the-pass/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/mightymattys/the-pass/compare/v0.9.1...v0.10.0
[0.9.1]: https://github.com/mightymattys/the-pass/compare/v0.9.0...v0.9.1
[0.9.0]: https://github.com/mightymattys/the-pass/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/mightymattys/the-pass/compare/v0.7.1...v0.8.0
[0.7.1]: https://github.com/mightymattys/the-pass/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/mightymattys/the-pass/compare/f9fb5e0...v0.7.0

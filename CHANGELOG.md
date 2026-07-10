# Changelog

All notable changes to The Pass are documented here. The project follows Semantic Versioning
and the Keep a Changelog structure.

## [Unreleased]

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

[Unreleased]: https://github.com/matk0shub/the-pass/compare/v0.7.1...HEAD
[0.7.1]: https://github.com/matk0shub/the-pass/compare/v0.7.0...v0.7.1
[0.7.0]: https://github.com/matk0shub/the-pass/compare/f9fb5e0...v0.7.0

# The Pass v0.9.1

`v0.9.1` is an installation and usability patch for the Codex/Claude plugin release.

## Fixed

- The repository now contains a Codex marketplace catalog, so
  `codex plugin marketplace add mightymattys/the-pass --ref v0.9.1` exposes
  `the-pass@the-pass-tools` instead of an empty marketplace.
- Claude Code now clones the public plugin source over HTTPS and no longer requires a configured
  GitHub SSH key for marketplace installation.
- Package, plugin, marketplace, and orchestration-policy version drift is rejected by public
  validation.

## Added

- A complete [Usage Guide](USAGE_GUIDE.md) with tested commands for CLI installation, Codex,
  Claude Code, the five-minute smoke, `/the-pass:run`, direct CLI workflows, external engines,
  data boundaries, cross-provider delegation, reports, exit codes, and immutable resume rules.
- Isolated installation evidence for both plugin runtimes and an end-to-end safe CLI smoke.

## Safety

This patch changes installation metadata, documentation, and version-consistency validation. It
does not add a live trading client, credentials, order transport, gate bypass, or candidate
approval.

See the [`v0.9.1` release audit](../../reports/RELEASE_AUDIT_0.9.1.md) for the verification matrix.

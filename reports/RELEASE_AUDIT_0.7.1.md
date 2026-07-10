# The Pass v0.7.1 Release Audit

Audit date: 2026-07-10
Audit verdict: `pass`
Open P0/P1 findings: none

## Purpose

This patch fixes the portable verification of GitHub release checksums. The `v0.7.0` artifact
bytes and digest values were correct, but checksum entries included a `dist/` prefix that is
absent after downloading individual GitHub assets.

## Fix

- `SHA256SUMS` is generated from inside `dist/`, so each entry contains the asset basename.
- Release audit and notes are selected from the pushed tag version.
- Published tags remain immutable; `v0.7.0` is preserved and marked as superseded.

## Regression Evidence

- Python 3.9 and 3.12 release matrices pass.
- Public repository, Ruff, lock, wheel/sdist, and clean-wheel validation pass.
- The downloaded wheel and sdist match `SHA256SUMS` using standard `sha256sum -c` semantics.
- No framework, candidate gate, adapter, risk, or live-boundary behavior changed.

## Authorization

The repository is authorized for the annotated `v0.7.1` tag after protected-branch CI. The
release workflow must block publication if tag/version matching, distribution validation, or
checksum generation fails.

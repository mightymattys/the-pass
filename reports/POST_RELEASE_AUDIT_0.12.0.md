# The Pass v0.12.0 Post-Release Audit

Audit date: 2026-07-15
Result: pass

## Publication Evidence

- Release: [v0.12.0](https://github.com/mightymattys/the-pass/releases/tag/v0.12.0)
- Tagged commit: `d5319fe7b0e6ac27dd99e75736107987ca4221b7`
- Release workflow: [run 29404395661](https://github.com/mightymattys/the-pass/actions/runs/29404395661)
- Python 3.9 validation: pass
- Python 3.12 validation: pass
- Distribution build/validation and GitHub publication: pass
- Release state: public, non-draft, non-prerelease

## Published Assets

| Asset | SHA-256 |
| --- | --- |
| `the_pass-0.12.0-py3-none-any.whl` | `11be3ba0e8288982cc87a8a3c45d7a4b1d2fbb34351946a1a9925cfc033d401b` |
| `the_pass-0.12.0.tar.gz` | `da8191133046a40b6f0606e2f333a15f0df1f542d921e89d4c62641643b8b954` |

The release also contains `SHA256SUMS` and the immutable release-candidate audit.

## Independent Download Verification

All assets were downloaded into a fresh temporary directory after publication.

- `shasum -a 256 -c SHA256SUMS`: both distributions pass.
- `scripts/validate_distribution.py` against the downloaded wheel: pass.
- Clean temporary virtual environment: CLI version, packaged schemas/policies, optional data and
  research imports, artifact validation, agent inspection, package validation, and receipt ledger
  smoke all pass.
- The downloaded wheel contains no repository-only evidence, fixtures, live-order transport, or
  credential loader patterns.

## Final State

Version `0.12.0` is usable from the documented GitHub release URL. The public live-order boundary
remains locked. No candidate strategy received promotion as part of this framework release.

# The Pass v0.10.0 Post-Release Audit

Verification date: 2026-07-12

Result: **PASS**

## Published Release

- Release: [The Pass v0.10.0](https://github.com/mightymattys/the-pass/releases/tag/v0.10.0)
- Release workflow: [run 29206594772](https://github.com/mightymattys/the-pass/actions/runs/29206594772)
- Source PR: [#13](https://github.com/mightymattys/the-pass/pull/13)
- Release preparation PR: [#14](https://github.com/mightymattys/the-pass/pull/14)
- Annotated tag: `v0.10.0`
- Tagged commit: `e86cffc9cfd8041dfddd18ff2e2c411660e80693`
- GitHub state: published, not draft, not prerelease

Both release validation jobs and the publish job passed. The release contains the wheel, source
distribution, checksum manifest, and pre-release audit.

## Asset Verification

Fresh downloads passed `shasum -a 256 -c SHA256SUMS`:

```text
0a93b7638e0bc6caf59f01d77cf05698cdf1432dabc1da222007373e14c55f10  the_pass-0.10.0-py3-none-any.whl
eb33ed30984ddb80e75734ca8b3658fd550c0f0213d8f99142ae6a5208aeb62f  the_pass-0.10.0.tar.gz
```

The freshly downloaded wheel passed `scripts/validate_distribution.py`, including clean isolated
installation, package-data checks, optional dependency imports, CLI version, template validation,
and locked live-boundary behavior.

## Final State

- `v0.10.0` is the latest published GitHub release.
- Python 3.9 and 3.12 release validation passed.
- The released CLI and both plugin manifests use version `0.10.0`.
- Current model catalogs are policy-bound and cannot fall back below the configured floor.
- No live order path, credential loader, authenticated venue channel, or gate bypass was added.

# The Pass v0.9.1 Post-Release Audit

Verification date: 2026-07-10

Result: **PASS**

## Published Release

- Release: [The Pass v0.9.1](https://github.com/matk0shub/the-pass/releases/tag/v0.9.1)
- Release workflow: [run 29111522079](https://github.com/matk0shub/the-pass/actions/runs/29111522079)
- Release PR: [#11](https://github.com/matk0shub/the-pass/pull/11)
- Annotated tag: `v0.9.1`
- Tagged commit: `c66932610213c74daf5ccd1391733ddc9bb70b04`
- GitHub state: latest release, not draft, not prerelease

The administrative review exception is preserved in
[RELEASE_AUDIT_0.9.1.md](RELEASE_AUDIT_0.9.1.md). Both release validation jobs and the publish job
passed.

## Asset Verification

All expected assets are present and fresh downloads pass `shasum -a 256 -c SHA256SUMS`:

```text
21e2f68a871d09f6bd02a7491fac6c533fe807af0ab0f77a5cf746db690891cf  the_pass-0.9.1-py3-none-any.whl
522739d16652567c25c3f1ed71afda9cdbdc7893cca22f52504aa1210236f596  the_pass-0.9.1.tar.gz
```

The downloaded wheel passed clean distribution validation. The exact user-level command from
`docs/public/USAGE_GUIDE.md` installed all research extras and returned `the-pass 0.9.1`.

## Published Plugin Installation

The documented commands were rerun against the published `v0.9.1` tag in new isolated profiles:

- Codex added `matk0shub/the-pass --ref v0.9.1`, discovered
  `the-pass@the-pass-tools`, installed version `0.9.1`, and enabled it.
- Claude added `matk0shub/the-pass`, cloned the pinned plugin over HTTPS without an SSH key,
  installed version `0.9.1`, and enabled it.
- Each installed archive contains exactly seven slash skills and four bounded Claude agent
  definitions.

This directly closes both installation failures reproduced from `v0.9.0`.

## Final State

- `v0.9.1` is the latest published GitHub release.
- Python 3.9 and 3.12 release validation passed.
- CLI, Codex marketplace, Claude HTTPS marketplace, wheel, sdist, and checksum paths are usable
  from the published release.
- The complete first-run procedure is documented in
  [the Usage Guide](../docs/public/USAGE_GUIDE.md).
- No live order path, credential loader, gate bypass, or candidate approval was added.

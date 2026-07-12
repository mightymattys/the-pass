# The Pass v0.9.0 Post-Release Audit

Verification date: 2026-07-10

Result: **PASS**

## Published Release

- Release: [The Pass v0.9.0](https://github.com/mightymattys/the-pass/releases/tag/v0.9.0)
- Release workflow: [run 29109347035](https://github.com/mightymattys/the-pass/actions/runs/29109347035)
- Release PR: [#9](https://github.com/mightymattys/the-pass/pull/9)
- Annotated tag: `v0.9.0`
- Tagged commit: `49a0c285c8d775446937ac0dd958e018f03fb52d`
- GitHub state: latest release, not draft, not prerelease

The administrative review exception and absence of an independent GitHub approval are preserved
in [RELEASE_AUDIT_0.9.0.md](RELEASE_AUDIT_0.9.0.md). Both release validation jobs and the publish
job passed.

## Asset Verification

All four expected release assets are present:

- `the_pass-0.9.0-py3-none-any.whl`
- `the_pass-0.9.0.tar.gz`
- `SHA256SUMS`
- `RELEASE_AUDIT_0.9.0.md`

Fresh downloads passed `shasum -a 256 -c SHA256SUMS`:

```text
a07c49155844b8f08ef60db944d05ce45d792a646a6acc69f235ca8a20c4bd46  the_pass-0.9.0-py3-none-any.whl
083e51dbf5b79ef79c78eb47051d3ceb82467ff746d4a49b1ad9046e2e36fd41  the_pass-0.9.0.tar.gz
```

The downloaded wheel independently passed `scripts/validate_distribution.py`, including a clean
installation outside the source checkout, packaged schema and policy lookup, CLI version and
artifact validation, receipt add/verify, and module import checks.

## Plugin Publication State

- The Claude marketplace manifest now resolves its pinned GitHub ref `v0.9.0`.
- Codex and Claude Code consume the same seven versioned skills from the published tag.
- Cross-provider execution remains explicit and depends on locally installed, authenticated
  provider CLIs.

## Final State

- `v0.9.0` is the latest published GitHub release.
- Python 3.9 and 3.12 release validation passed.
- Wheel, sdist, checksum generation, release publication, fresh download, and clean installation
  passed.
- The released public core contains no live order path or credential loader.
- Framework completion remains separate from every strategy candidate result.

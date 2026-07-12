# Release Process

## Prepare

1. Work on a `codex/` prefixed branch and review the complete diff.
2. Update `CHANGELOG.md`, package version, completion audit, and remaining-work status.
3. Run Python 3.9 and 3.12 tests, public validation, Ruff, lock check, and distribution checks.
4. Confirm no candidate result is represented as a framework capability result.
5. Create `docs/public/RELEASE_NOTES_vX.Y.Z.md` and `reports/RELEASE_AUDIT_X.Y.Z.md`; the release
   workflow resolves both paths from the tag and fails if either is absent.
6. Open a pull request and record the safety impact and exact verification commands.

## Build and Merge

1. Merge only after required protected-branch checks pass and review findings are resolved.
2. Build wheel and sdist in CI, not from an unreviewed workstation state.
3. Verify packaged schemas, policies, CLI behavior, and absence of live-order paths.
4. Do not use administrator bypass to replace the required independent review unless the
   repository owner explicitly authorizes an exception for that release. Record the exception,
   missing review, green required checks, and resulting merge commit in the release audit.

## Tag and Publish

1. Create and push an annotated `vX.Y.Z` tag on the reviewed `main` commit.
2. Let `.github/workflows/release.yml` rerun the Python matrix, confirm the tag/package version,
   build and validate the distributions, and create the GitHub Release.
3. Require the workflow-created release to contain the wheel, sdist, SHA-256 checksums, and
   matching release audit; do not replace these with workstation-built assets.
4. Download the published assets into a fresh directory, verify `SHA256SUMS`, and validate the
   downloaded wheel outside the checkout.
5. Record the workflow URL, tagged commit, asset hashes, and clean-install result in
   `reports/POST_RELEASE_AUDIT_X.Y.Z.md`; then update current installation documentation.
6. PyPI publication requires a separate explicit instruction.

## Rollback

Never rewrite a published tag. Mark a faulty release as withdrawn, preserve its evidence,
freeze affected automation, and fix forward with a patch release. A release rollback cannot
alter prior receipts or candidate gate decisions.

# The Pass v0.13.0 Post-Release Audit

Audit date: 2026-07-15
Result: pass

## Publication Identity

| Item | Evidence |
| --- | --- |
| Pull request | [#23](https://github.com/mightymattys/the-pass/pull/23) |
| Tagged merge commit | `f2f58c08752c72238a60a238f5829effce14fe8f` |
| Tag | `v0.13.0`, annotated and resolving to the tagged merge commit |
| Release | [The Pass v0.13.0](https://github.com/mightymattys/the-pass/releases/tag/v0.13.0) |
| Final PR CI | [29408241767](https://github.com/mightymattys/the-pass/actions/runs/29408241767), Python 3.9 and 3.12 passed |
| Main CI | [29408348106](https://github.com/mightymattys/the-pass/actions/runs/29408348106), Python 3.9 and 3.12 passed |
| Release workflow | [29408453692](https://github.com/mightymattys/the-pass/actions/runs/29408453692), validation and publication passed |

The PR had no external approving GitHub review. The repository owner explicitly authorized
deployment, both required CI contexts passed on the final audit commit, and the documented
administrative review exception was recorded in the tagged release audit before merge.

## Published Assets

| Asset | SHA-256 |
| --- | --- |
| `the_pass-0.13.0-py3-none-any.whl` | `8d4ad75547abfb9b35fafe322636d5eb35919b4327ca136708b92ae9ec2a589d` |
| `the_pass-0.13.0.tar.gz` | `71323f994a30316649805d79aeb78e5cc29de3c61027f747b934df575be71c95` |
| `SHA256SUMS` | `b7bcb02961a2d91c7776b6885731f4cc5148eeadce6e27e183c1e3db3492a23e` |
| `RELEASE_AUDIT_0.13.0.md` | `01bbf79cdc9909f02ff1f80765898b0db0241cea731faefd70c2af3273a987d1` |

## Independent Download Verification

All assets were downloaded from the published GitHub Release into a fresh temporary directory.
`shasum -a 256 -c SHA256SUMS` passed for the wheel and source distribution. The downloaded wheel
then passed `scripts/validate_distribution.py`, including:

- clean virtual-environment installation with `data`, `research`, and `paper` extras;
- installed CLI version and stable JSON-envelope checks;
- exact packaged schema and policy inventory checks;
- package and receipt-ledger validation from the installed CLI;
- forbidden live-order and credential-pattern scan.

## Final Result

The release tag, source version, plugin versions, wheel metadata, schemas, policies, checksums, and
documentation agree on `0.13.0`. No live-order path was introduced. The repository release is
published and the trust-boundary hardening plan is complete.

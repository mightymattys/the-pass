# System Hardening Audit

Date: 2026-07-09.
Scope: plugin skills, workflow artifacts, package validation, and receipt integrity.

## Verdict

`pass after fixes` for the public research-framework scope.

This verdict does not claim that a strategy has edge or that any adapter is ready for live
trading.

## Confirmed Findings

1. All 11 skill frontmatter names were invalid.
   - They repeated the plugin namespace (`the-pass:mise`) instead of using the folder name
     (`mise`).
   - The canonical skill validator rejected every skill even though the plugin-level validator
     passed.
   - Fixed all names and made public-repo validation parse and verify frontmatter structurally.

2. Nine slash-command outputs had templates but no schemas.
   - Screen reports, findings, refire tickets, simmer laps, paper plans, observation manifests,
     divergence reports, approval packs, and receipt summaries could not be validated by the CLI.
   - Added schemas, type inference, state-dependent checks, skill commands, and regression tests.

3. Package links were existence checks, not identity checks.
   - A run receipt could point `strategy_spec` at another existing artifact and still pass.
   - A package with both JSON and YAML versions of one artifact was silently resolved by
     extension order.
   - Fixed by requiring exact canonical links and rejecting ambiguous artifact duplicates.

4. Receipt verification protected ledger lines but not recorded artifacts.
   - Editing an artifact after `receipts add` did not break `receipts verify`.
   - The same package could not be recorded at two distinct gates because deduplication ignored
     the gate.
   - Fixed artifact hash verification, path containment checks, gate-aware idempotency, and gate
     name validation.

5. `taste` mixed a command state with the verdict vocabulary.
   - Clarified that `pass` is a command exit state and maps to `paper_candidate` in a passed
     `research_gate` verdict. Later gates use their own workflow artifacts.
   - Canonical gate IDs are now documented consistently.

6. `paper_candidate` did not mechanically prove independent review.
   - Promotion now requires schema-valid findings for a passed `research_gate`, an independent
     reviewer, matching verdict ownership, calculated gross/net evidence, a null/random baseline,
     no failed gates, and a research- or paper-mode adapter.

7. Research hypotheses had no artifact contract.
   - Added the hypothesis template and schema so source references, edge mechanism, next test,
     baseline, falsification criteria, risks, blockers, and kill conditions survive the handoff
     from `research` to `spec`.

8. Approval packs could encode a human decision as already approved.
   - Approval-pack safety flags now prove that the artifact grants no approval or live path,
     requested gates are constrained, and all required human decisions remain pending.

9. Promotion evidence accepted non-null placeholders as calculations.
   - `paper_candidate` now requires finite numeric gross/net evidence, at least one trade, a
     substantive null/random baseline result, explicit execution assumptions, and internally
     consistent state-dependent verdict fields.

10. Filesystem boundaries did not match the documented safety model.
    - Package artifacts may no longer escape through symlinks, and public validation now scans
      tracked plus non-ignored candidate files without rejecting intentionally ignored local data.

11. Data and cost evidence was structurally under-specified.
    - Data manifests now require provider/license/coverage/schema/quality/fingerprint detail.
      Promotion cost waterfalls require numeric fee, spread, and slippage components plus an
      exact gross-to-net reconciliation and explicit model assumptions.

12. Promotion did not enforce OOS and overfitting evidence from the research plan.
    - `paper_candidate` now requires a named holdout window, out-of-sample or walk-forward
      evaluation, numeric DSR/PSR or PBO, stress results, parameter stability, and a predefined
      train/test and holdout policy.

13. Promotion could cite empty or unread source notes.
    - Source notes now require substantive claims, evidence, limitations, applicability, tests,
      failure modes, and system requirements. Promotion accepts only reviewed or implemented
      notes.

14. `research_ready` had no enforceable StrategySpec state contract.
    - The command state now maps explicitly to `StrategySpec.status: research`, which requires
      complete market, edge, data, signal, execution, risk, validation, gate, done, and kill
      fields while `draft` remains editable.

15. `backtest_candidate` screens could escalate without a real sample.
    - Escalation now requires a dated sample, instrument, positive observation count, recorded
      variants, baseline comparison, conservative cost assumptions, gross/net results, and
      robustness notes.

## Verification

- Public repository validator passes.
- All 11 skills pass the canonical skill validator.
- Plugin manifest passes the plugin validator.
- All registered v1/v2 artifact schemas pass Draft 2020-12 schema checks.
- Ninety-two unit tests pass, including mutation tests for false links, duplicate artifacts,
  unresolved blockers, chronology, false gate labels, ledger edits, and post-receipt artifact edits.
- Both synthetic packages, all adapter descriptors, and the receipt CLI workflow pass.
- GitHub Actions passes on Python 3.9 and 3.12 using Node 24-based action runtimes.

## Residual Boundary

The repo is a robust public workflow framework, not a finished trading platform. A real
collector, event-driven runner, paper observer, risk engine, and any live-capable adapter remain
separate implementations that must satisfy these gates before use.

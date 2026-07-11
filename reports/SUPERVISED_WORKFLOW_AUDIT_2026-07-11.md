# Supervised Workflow and Model Routing Audit

Audit date: 2026-07-11

Source version: `0.10.0`

Branch: `codex/repository-hardening-audit`

## Verdict

The supervised non-live workflow implementation is complete and locally release-ready. The
repository now has a mechanical liveness supervisor, stage-aware provider/model routing, explicit
inspect-versus-execute behavior, deterministic gate authority, and regression coverage for
premature or invalid termination.

No strategy candidate was promoted by this audit. Live execution remains technically locked.

## Implemented Controls

- `the-pass workflow execute` supervises one transition per cycle and stops only at `complete`,
  `waiting`, `blocked`, or `killed`.
- `--driver auto` selects Codex or Claude by stage, profile, capability, availability, and reviewer
  separation policy.
- Preflight and gate recording are deterministic; no model creates its own gate decision.
- A successful child response without state progress fails.
- Illegal transitions, counter jumps, missing exact-package evidence, timeout, output overflow, and
  cycle exhaustion fail without a completion claim.
- Every cycle records before/after state fingerprints, route policy fingerprint, provider/model,
  bounded process metadata, and output hashes.
- Blocked/waiting workflows are not automatically resumed and failed provider calls are not
  retried through another paid model.
- Codex and Claude auto-driver processes receive no unrelated MCP servers, connectors, browser,
  hooks, provider plugins, or nested agent delegation.
- Auto-driver child environments retain only local CLI/config essentials and do not inherit venue
  keys or direct provider API-key variables. Supervisor reports cannot overwrite workflow state or
  be placed outside the run-state directory.

## Routing Policy

| Work | Preferred route |
| --- | --- |
| Research synthesis | Claude deep |
| Data, screen, backtest, implementation | Codex deep for critical work |
| Robustness/statistical skepticism | Claude deep |
| Independent review | provider different from actual implementer |
| Paper and risk packaging | Codex balanced/deep |
| Preflight and gate recording | deterministic supervisor |

Codex requests use only `gpt-5.6-luna`, `gpt-5.6-terra`, and `gpt-5.6-sol`. Claude requests use
only `claude-sonnet-5`, `claude-opus-4-8`, and `claude-fable-5`. The policy enforces two-to-three
current models per provider and rejects older Codex families. Arbitrary model IDs cannot enter
through an AgentTask.

## Verification Matrix

| Check | Result |
| --- | --- |
| Ruff | pass |
| Public repository validator | pass |
| Python default environment | 197 tests pass |
| Python 3.9 isolated | 197 tests pass |
| Python 3.12 isolated | 197 tests pass |
| Roadmap/corpus/D1/B2/V3/P4 validation | pass |
| `uv lock --check` | pass |
| Wheel and sdist `0.10.0` | pass |
| Clean installed-wheel validation | pass |
| Claude plugin and marketplace strict validation | pass |
| Supervisor inspect no-side-effect smoke | pass |
| Codex GPT-5.6 authenticated smoke | Luna, Terra, and Sol pass |
| Claude current-model authenticated smoke | Sonnet 5, Opus 4.8, and Fable 5 blocked: local Claude CLI returned HTTP 401 |

The Claude result is an external account state, not a framework defect. `agents doctor` correctly
reports `authentication_checked: false`; it never converts binary availability into an access
claim. Until the user authenticates Claude, a run can be constrained with
`--available-provider codex` or will fail closed when a Claude stage is selected.

## Residual Boundaries

- The auto driver is an explicitly trusted local mode with workspace tools. The supervisor
  validates workflow state and gate authority, but it is not an operating-system sandbox for an
  arbitrary custom driver.
- Provider authentication and entitlement can change outside the repository and are checked only
  by an actual provider call.
- A valid `blocked`, `waiting`, or `killed` strategy is a completed research outcome even though it
  has no positive backtest result.
- Paper windows, licensed futures archives, and real independent candidate evidence remain runtime
  inputs rather than missing framework implementation.
- Real order transport, authenticated venue clients, credential loaders, and `live_gate` approval
  remain absent and forbidden.

## Conclusion

The earlier gap is closed: an agent's prose can no longer be the only reason an end-to-end run
stops or claims completion. The supervisor requires durable checkpoint progress and the exact
recorded target-gate pass. Model selection is versioned, stage-specific, capability-checked, and
auditable rather than left to ad hoc prompt choice.

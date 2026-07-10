# ADR-0011: Capability-Aware Model Routing

Status: accepted

Date: 2026-07-10

Owner: automation_engineer

## Context

The cross-provider broker originally inherited each CLI's default model. That was portable, but it
made cost, latency, and expected capability implicit. A routine source lookup and a critical audit
could therefore use the same model, while a local user setting could silently change the choice.

The provider contracts are different. Codex documents Luna as the efficient model for clear,
repeatable work, Terra as the everyday workhorse, and Sol for ambiguous or high-value work. Claude
Code documents Haiku for simple low-cost tasks, Sonnet for everyday coding, and Opus for complex
reasoning. Both CLIs expose explicit model and reasoning-effort flags.

Sources reviewed on 2026-07-10:

- [Codex models](https://developers.openai.com/codex/models)
- [Codex configuration reference](https://developers.openai.com/codex/config-reference)
- [Claude Code model configuration](https://code.claude.com/docs/en/model-config)
- [Claude Code cost guidance](https://code.claude.com/docs/en/costs)

## Decision

The broker owns a versioned capability catalog in `config/agent-orchestration.v1.yaml` and its
packaged byte-identical copy. Tasks choose a structured `workload_class` and a minimum
`model_profile`; they never provide an arbitrary model ID.

Profiles are:

| Profile | Codex | Claude | Intended work |
| --- | --- | --- | --- |
| `economy` | `gpt-5.6-luna`, low | `haiku`, provider default effort | routine, well-specified read-only work |
| `balanced` | `gpt-5.6-terra`, medium | `sonnet`, medium | normal research, review, and implementation |
| `deep` | `gpt-5.6-sol`, high | `opus`, high | complex, ambiguous, or high-value work |

`critical` workload uses the `deep` model and raises effort to the catalog's critical setting.
`auto` workload resolves conservatively to `standard`. Implementation and native-subagent runs
have a `balanced` floor. An explicit profile is a minimum: it can raise capability but cannot lower
the workload, role, write-mode, or native-subagent floor.

The router checks the selected catalog entry against role capabilities before process creation.
`agents inspect` exposes the resolved model, effort, capabilities, and rationale without a model
call. Every `agent_run` stores the same selection and a SHA-256 fingerprint of the routing policy.
The provider argv must match that receipt or semantic validation fails.

Claude family aliases are intentionally rolling aliases managed by Claude Code. Codex model IDs
are reviewed release inputs. Public validation rejects known deprecated Codex IDs and incomplete
catalogs. `agents doctor` reports the configured profiles and CLI version but does not claim that
the account can access every model.

## Consequences

- Routine work can use a faster, cheaper model without weakening implementation or audit floors.
- Complex work gets a stronger model and more reasoning by deterministic policy rather than prompt
  wording.
- Model choice is visible before execution and auditable afterward.
- Provider releases require a catalog review, tests, and an updated review date.
- A provider can still reject an unavailable model or apply its documented account-level alias
  behavior; the broker records the requested model and fails rather than retrying another model.

## Alternatives Rejected

- Provider defaults: rejected because local settings and subscription defaults are not auditable.
- Free-text complexity classification: rejected because routing would be nondeterministic and easy
  to manipulate.
- User-supplied model IDs: rejected because tasks could select deprecated, untested, or
  capability-incompatible models.
- Always use the strongest model: rejected because most bounded tasks do not justify the latency
  and cost.
- Automatic fallback/retry: rejected because it breaks the one-attempt budget and obscures which
  model produced the evidence.

## Validation

- A matrix test covers both providers, every workload tier, explicit upgrades, worktree floors,
  native-subagent floors, and critical effort.
- Missing required capabilities fail before provider execution.
- `agent_run` validation rejects model or effort values that differ from sanitized argv.
- Source and packaged policies and schemas are byte-identical.
- Real provider smoke verifies the selected CLI flags on authenticated local installations.

## Review Trigger

Review the catalog on every release and whenever either provider deprecates a selected model,
changes effort semantics, or changes alias behavior. Changing profile meaning or allowing fallback
requires a new ADR.

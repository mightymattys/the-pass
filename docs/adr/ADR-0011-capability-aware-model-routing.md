# ADR-0011: Capability-Aware Model Routing

Status: accepted

Date: 2026-07-10; model catalog amended 2026-07-11

Owner: automation_engineer

## Context

The cross-provider broker originally inherited each CLI's default model. That was portable, but it
made cost, latency, and expected capability implicit. A routine source lookup and a critical audit
could therefore use the same model, while a local user setting could silently change the choice.

The provider contracts are different. OpenAI's current frontier family has three explicit tiers:
GPT-5.6 Luna for cost-sensitive work, Terra for balanced work, and Sol for the most complex work.
Anthropic's current set includes Claude Sonnet 5, Opus 4.8, and Fable 5. Both CLIs expose explicit
model and reasoning-effort flags.

Sources reviewed on 2026-07-11:

- [OpenAI models](https://developers.openai.com/api/docs/models)
- [Codex configuration reference](https://developers.openai.com/codex/config-reference)
- [Claude models overview](https://platform.claude.com/docs/en/about-claude/models/overview)
- [Claude model IDs and versioning](https://platform.claude.com/docs/en/about-claude/models/model-ids-and-versions)

## Decision

The broker owns a versioned capability catalog in `config/agent-orchestration.v1.yaml` and its
packaged byte-identical copy. Tasks choose a structured `workload_class` and a minimum
`model_profile`; they never provide an arbitrary model ID.

Profiles are:

| Profile | Codex | Claude | Intended work |
| --- | --- | --- | --- |
| `economy` | `gpt-5.6-luna`, low | `claude-sonnet-5`, provider default effort | routine, well-specified work |
| `balanced` | `gpt-5.6-terra`, medium | `claude-opus-4-8`, medium | normal research, review, and implementation |
| `deep` | `gpt-5.6-sol`, high | `claude-fable-5`, high | complex, ambiguous, or high-value work |

`critical` workload uses the `deep` model and raises effort to the catalog's critical setting.
`auto` workload resolves conservatively to `standard`. Implementation and native-subagent runs
have a `balanced` floor. An explicit profile is a minimum: it can raise capability but cannot lower
the workload, role, write-mode, or native-subagent floor.

The router checks the selected catalog entry against role capabilities before process creation.
`agents inspect` exposes the resolved model, effort, capabilities, and rationale without a model
call. Every `agent_run` stores the same selection and a SHA-256 fingerprint of the routing policy.
The provider argv must match that receipt or semantic validation fails.

Both providers use explicit current model IDs as reviewed release inputs. Each provider must expose
exactly two or three distinct models, every profile must resolve to that allowlist, and the Codex
catalog has a mechanical `gpt-5.6` minimum-family check. This intentionally rejects older low-cost
fallbacks. `agents doctor` reports configured profiles and CLI versions but does not claim that the
account can access every model.

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

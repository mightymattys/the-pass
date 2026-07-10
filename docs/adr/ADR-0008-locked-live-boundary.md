# ADR-0008: Locked Live Boundary

Status: Accepted  
Date: 2026-07-10

## Decision

The public core exposes only locked execution contracts, config diff, dry-run proof, and
live risk envelopes. It contains no external transaction transport, authenticated account
client, or credential loader.

The public `HumanDecision` schema can represent only `blocked` and can never grant approval.
The public dry-run gateway has `transport_available = false` and every proof records no
external side effects.

## Unlock Preconditions

Any future venue capability requires a new explicit user instruction and a separate
accepted venue-specific ADR tied to venue, account scope, adapter, and config hash. Before
that ADR, the live gate remains safety exit code 3.

Required preconditions include threat modeling, legal/provider review, a credential
boundary, dry-run proof, monitoring, rollback, incident response, and a separate
least-privilege process inaccessible to research agents.

## L6 Boundary

Even after a future unlock, escalation requires TCA, adverse-selection analysis, fixed
trade-count review, and live/paper tolerance. Loss, divergence, data-health, or operational
safety breaches freeze the strategy.

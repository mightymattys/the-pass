"""Credential-free virtual paper worker process."""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
from pathlib import Path

from the_pass.data.contracts import CanonicalEvent, canonical_value
from the_pass.engine.costs import LinearCostModel
from the_pass.engine.fills import BarFillModel
from the_pass.engine.simulator import EventSimulator
from the_pass.engine.workflows import make_baseline_strategy
from the_pass.risk import VersionedRiskPolicy


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategy", required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--risk-policy", type=Path, required=True)
    parser.add_argument("--config-hash", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    events = [CanonicalEvent.from_dict(json.loads(line)) for line in args.events.read_text(encoding="utf-8").splitlines() if line]
    policy_artifact = json.loads(args.risk_policy.read_text(encoding="utf-8"))
    risk_policy = VersionedRiskPolicy.from_artifact(policy_artifact)
    result = EventSimulator(
        fill_model=BarFillModel(Decimal(5)),
        cost_model=LinearCostModel(Decimal("0.001")),
        initial_cash=Decimal("100000"),
        risk_policy=risk_policy,
    ).run(make_baseline_strategy(args.strategy), events)
    document = {
        "schema_version": 1,
        "status": "complete" if not result.rejected else "frozen",
        "strategy_name": args.strategy,
        "strategy_id": result.strategy_id,
        "config_hash": args.config_hash,
        "process_isolated": True,
        "network_clients_loaded": any(name in sys.modules for name in ("httpx", "websockets")),
        "credentials_present": False,
        "signals": result.signals,
        "decision_journal": [
            {
                "intent_id": intent.intent_id,
                "decision_time_ns": intent.decision_time_ns,
                "instrument_id": intent.instrument_id,
                "side": intent.side,
                "quantity": intent.quantity,
            }
            for intent in result.intents
        ],
        "simulated_intents": [intent.__dict__ for intent in result.intents],
        "fills": [fill.__dict__ for fill in result.fills],
        "missed_fills": result.missed,
        "rejected": result.rejected,
        "outages": [],
        "latency_ns": [event.receive_time_ns - event.event_time_ns for event in events],
        "risk_events": result.rejected,
        "cost_components": result.cost_components,
        "final_snapshot": result.final_snapshot,
    }
    args.output.write_text(
        json.dumps(canonical_value(document), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Deterministic event simulator with ordered streaming replay."""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable, Iterator

from the_pass.data.contracts import (
    CanonicalEvent,
    EventType,
    stable_fingerprint,
)

from .contracts import (
    CostModel,
    FillModel,
    RiskPolicy,
    RunnerContext,
    RunnerResult,
    SimulatedIntent,
    StrategyRunner,
)
from .portfolio import AccountingPortfolio


class AllowAllRiskPolicy:
    def allow(
        self, intent: SimulatedIntent, portfolio: AccountingPortfolio
    ) -> tuple[bool, str]:
        return True, ""


class EventSimulator:
    MAX_INTENTS_PER_EVENT = 10_000

    def __init__(
        self,
        *,
        fill_model: FillModel,
        cost_model: CostModel,
        initial_cash: Decimal = Decimal("100000"),
        risk_policy: RiskPolicy | None = None,
        equity_sampling_interval: int = 1,
    ) -> None:
        self.fill_model = fill_model
        self.cost_model = cost_model
        self.initial_cash = initial_cash
        self.risk_policy = risk_policy or AllowAllRiskPolicy()
        if (
            not isinstance(equity_sampling_interval, int)
            or isinstance(equity_sampling_interval, bool)
            or equity_sampling_interval <= 0
        ):
            raise ValueError(
                "equity_sampling_interval must be a positive integer"
            )
        self.equity_sampling_interval = equity_sampling_interval

    def run(
        self, strategy: StrategyRunner, events: Iterable[CanonicalEvent]
    ) -> RunnerResult:
        ordered = sorted(events, key=CanonicalEvent.sort_key)
        return self.run_ordered(
            strategy,
            ordered,
            total_events=len(ordered),
            instrument_ids={event.instrument_id for event in ordered},
        )

    def run_ordered(
        self,
        strategy: StrategyRunner,
        events: Iterable[CanonicalEvent],
        *,
        total_events: int,
        instrument_ids: set[str],
        checkpoint: dict[str, object] | None = None,
        checkpoint_mode: bool = False,
    ) -> RunnerResult:
        if total_events <= 0:
            raise ValueError("event simulator requires events")
        if (
            not isinstance(getattr(strategy, "strategy_id", None), str)
            or not strategy.strategy_id
        ):
            raise ValueError("strategy_id must be a non-empty string")
        portfolio = (
            AccountingPortfolio.from_state(checkpoint["portfolio"])
            if checkpoint is not None
            else AccountingPortfolio(self.initial_cash)
        )
        checkpoint_pending = (
            list(checkpoint["pending"]) if checkpoint is not None else []
        )
        pending: list[SimulatedIntent] = (
            [
                SimulatedIntent(
                    intent_id=str(row["intent_id"]),
                    instrument_id=str(row["instrument_id"]),
                    side=str(row["side"]),
                    quantity=Decimal(str(row["quantity"])),
                    decision_time_ns=int(row["decision_time_ns"]),
                    intent_type=str(row["intent_type"]),
                    limit_price=(
                        Decimal(str(row["limit_price"]))
                        if row.get("limit_price") is not None
                        else None
                    ),
                )
                for row in checkpoint_pending
            ]
            if checkpoint is not None
            else []
        )
        pending_reasons = {
            str(row["intent_id"]): str(row.get("latest_outcome_reason", ""))
            for row in checkpoint_pending
            if row.get("latest_outcome_reason")
        }
        all_intents: list[SimulatedIntent] = []
        fills = []
        rejected: list[dict[str, object]] = []
        missed: list[dict[str, object]] = []
        equity_curve: list[dict[str, object]] = (
            list(checkpoint.get("equity_curve", []))
            if checkpoint is not None
            else []
        )
        cost_names = (
                "fees",
                "spread",
                "slippage",
                "impact",
                "funding",
                "borrow",
                "roll",
                "rejects_or_missed_fills",
        )
        costs = (
            {
                name: Decimal(str(checkpoint["costs"].get(name, "0")))
                for name in cost_names
            }
            if checkpoint is not None
            else {name: Decimal(0) for name in cost_names}
        )
        lifecycle_events: list[dict[str, object]] = []
        signals = int(checkpoint["signals"]) if checkpoint is not None else 0
        intent_ids: set[str] = (
            set(str(value) for value in checkpoint["intent_ids"])
            if checkpoint is not None
            else set()
        )
        event_offset = (
            int(checkpoint["event_offset"]) if checkpoint is not None else 0
        )
        checkpoint_last_key = (
            tuple(checkpoint["last_event_key"])
            if checkpoint is not None
            else None
        )
        previous_receive_time_ns = (
            int(checkpoint["last_receive_time_ns"])
            if checkpoint is not None
            and checkpoint.get("last_receive_time_ns") is not None
            else None
        )
        previous_ingest_id = (
            str(checkpoint["last_ingest_id"])
            if checkpoint is not None and checkpoint.get("last_ingest_id")
            else None
        )
        previous_key: tuple[object, ...] | None = checkpoint_last_key
        last_event: CanonicalEvent | None = None

        iterator: Iterator[CanonicalEvent] = iter(events)
        processed = 0
        for index, event in enumerate(iterator):
            if not isinstance(event, CanonicalEvent):
                raise TypeError("event stream must contain CanonicalEvent values")
            key = event.sort_key()
            if (
                processed == 0
                and checkpoint_last_key is not None
                and key <= checkpoint_last_key
            ):
                raise ValueError(
                    "checkpoint continuation must start after the previous event"
                )
            if previous_key is not None and key < previous_key:
                raise ValueError("ordered event stream is not deterministic")
            if (
                previous_receive_time_ns is not None
                and event.receive_time_ns < previous_receive_time_ns
            ):
                raise ValueError(
                    "receive_time_ns decreased between "
                    f"{previous_ingest_id or '<checkpoint event>'} "
                    f"({previous_receive_time_ns}) and {event.ingest_id} "
                    f"({event.receive_time_ns}); run the receive_time_inversion quality check"
                )
            previous_key = key
            previous_receive_time_ns = event.receive_time_ns
            previous_ingest_id = event.ingest_id
            last_event = event
            processed += 1
            portfolio.begin_event(event.receive_time_ns)
            begin_fill_event = getattr(self.fill_model, "begin_event", None)
            if begin_fill_event is not None:
                begin_fill_event(event)

            if event.event_type == EventType.INSTRUMENT_DEFINITION:
                portfolio.register_instrument(
                    event.instrument_id,
                    instrument_type=str(
                        event.payload.get("instrument_type", "spot")
                    ),
                    multiplier=Decimal(
                        str(event.payload.get("multiplier", "1"))
                    ),
                )
            elif event.event_type == EventType.FUNDING:
                amount = portfolio.apply_funding_rate(
                    event.instrument_id,
                    rate=Decimal(str(event.payload["rate"])),
                    price=(
                        Decimal(str(event.payload["price"]))
                        if "price" in event.payload
                        else None
                    ),
                )
                costs["funding"] += amount
                borrow_cost = Decimal(
                    str(event.payload.get("borrow_cost", "0"))
                )
                if borrow_cost:
                    portfolio.apply_carry_cost("borrow", borrow_cost)
                    costs["borrow"] += borrow_cost
                lifecycle_events.append(
                    {
                        "event_type": "funding",
                        "instrument_id": event.instrument_id,
                        "amount": amount,
                        "borrow_cost": borrow_cost,
                        "evidence": event.ingest_id,
                        "event_time_ns": event.receive_time_ns,
                    }
                )
            elif event.event_type == EventType.SETTLEMENT:
                raw_settlement = event.payload.get(
                    "settlement_price", event.payload.get("price")
                )
                if raw_settlement is None:
                    raise ValueError(
                        "settlement event requires settlement_price"
                    )
                settlement_price = Decimal(str(raw_settlement))
                realized = portfolio.settle_position(
                    event.instrument_id, settlement_price
                )
                roll_cost = Decimal(
                    str(event.payload.get("roll_cost", "0"))
                )
                if roll_cost:
                    portfolio.apply_carry_cost("roll", roll_cost)
                    costs["roll"] += roll_cost
                lifecycle_events.append(
                    {
                        "event_type": "settlement",
                        "instrument_id": event.instrument_id,
                        "settlement_price": settlement_price,
                        "realized_pnl": realized,
                        "roll_cost": roll_cost,
                        "evidence": event.ingest_id,
                        "event_time_ns": event.receive_time_ns,
                    }
                )

            still_pending = []
            next_pending_reasons: dict[str, str] = {}
            for intent in pending:
                outcome = self.fill_model.evaluate(
                    intent, event, self.cost_model
                )
                for fill in outcome.fills:
                    portfolio.apply_fill(fill)
                    fills.append(fill)
                    costs["fees"] += fill.fee
                    costs["spread"] += fill.spread_cost
                    costs["slippage"] += fill.slippage_cost
                    costs["impact"] += fill.impact_cost
                if outcome.status in {"rejected", "partial_rejected"}:
                    rejected.append(
                        {
                            "intent_id": intent.intent_id,
                            "quantity": outcome.remaining_quantity,
                            "reason": outcome.reason,
                        }
                    )
                elif outcome.status == "missed":
                    missed.append(
                        {
                            "intent_id": intent.intent_id,
                            "quantity": outcome.remaining_quantity,
                            "reason": outcome.reason,
                        }
                    )
                elif outcome.remaining_quantity > 0:
                    latest_reason = (
                        outcome.reason
                        or pending_reasons.get(intent.intent_id, "")
                    )
                    still_pending.append(
                        SimulatedIntent(
                            intent.intent_id,
                            intent.instrument_id,
                            intent.side,
                            outcome.remaining_quantity,
                            intent.decision_time_ns,
                            intent.intent_type,
                            intent.limit_price,
                        )
                    )
                    if latest_reason:
                        next_pending_reasons[intent.intent_id] = latest_reason
            pending = still_pending
            pending_reasons = next_pending_reasons

            mark_value = event.payload.get(
                "close", event.payload.get("price")
            )
            if mark_value is None and event.event_type in {
                EventType.BOOK_SNAPSHOT,
                EventType.BOOK_DELTA,
            }:
                bids = event.payload.get("bids") or []
                asks = event.payload.get("asks") or []
                if bids and asks:
                    best_bid = max(
                        Decimal(str(level[0])) for level in bids
                    )
                    best_ask = min(
                        Decimal(str(level[0])) for level in asks
                    )
                    if best_bid > 0 and best_ask > best_bid:
                        mark_value = (best_bid + best_ask) / Decimal(2)
            snapshot = None
            if mark_value is not None and event.event_type in {
                EventType.BAR,
                EventType.TRADE,
                EventType.BOOK_SNAPSHOT,
                EventType.BOOK_DELTA,
            }:
                snapshot = portfolio.mark(
                    event.instrument_id,
                    Decimal(str(mark_value)),
                    event.receive_time_ns,
                )
            elif event.event_type in {
                EventType.FUNDING,
                EventType.SETTLEMENT,
            }:
                snapshot = portfolio.snapshot(event.receive_time_ns)
            absolute_index = event_offset + index
            if snapshot is not None and (
                absolute_index % self.equity_sampling_interval == 0
                or (not checkpoint_mode and index == total_events - 1)
            ):
                equity_curve.append(snapshot)

            context = RunnerContext(
                event_index=event_offset + index,
                total_events=event_offset + total_events,
                decision_time_ns=event.receive_time_ns,
                positions=portfolio.positions,
                marks=dict(portfolio.marks),
            )
            event_before = stable_fingerprint(event.as_dict())
            proposed = strategy.on_event(event, context)
            try:
                new_intents = list(proposed)
            except TypeError as exc:
                raise TypeError(
                    "strategy on_event must return an iterable of SimulatedIntent"
                ) from exc
            if stable_fingerprint(event.as_dict()) != event_before:
                raise ValueError("strategy mutated its canonical input event")
            if len(new_intents) > self.MAX_INTENTS_PER_EVENT:
                raise ValueError(
                    "strategy exceeded the per-event intent limit"
                )
            signals += len(new_intents)
            for intent in new_intents:
                if not isinstance(intent, SimulatedIntent):
                    raise TypeError(
                        "strategy must return only SimulatedIntent objects"
                    )
                if intent.instrument_id not in instrument_ids:
                    raise ValueError(
                        "strategy intent references an instrument outside the dataset"
                    )
                if intent.intent_id in intent_ids:
                    raise ValueError(
                        f"duplicate strategy intent_id: {intent.intent_id}"
                    )
                intent_ids.add(intent.intent_id)
                if intent.decision_time_ns != event.receive_time_ns:
                    raise ValueError(
                        "strategy intent decision time must equal current receive time"
                    )
                allowed, reason = self.risk_policy.allow(intent, portfolio)
                if not allowed:
                    rejected.append(
                        {
                            "intent_id": intent.intent_id,
                            "quantity": intent.quantity,
                            "reason": reason,
                        }
                    )
                    continue
                pending.append(intent)
                all_intents.append(intent)

        if processed != total_events or last_event is None:
            raise ValueError("event stream count differs from declared total")
        if not checkpoint_mode:
            for intent in pending:
                missed.append(
                    {
                        "intent_id": intent.intent_id,
                        "quantity": intent.quantity,
                        "reason": pending_reasons.get(
                            intent.intent_id, "no subsequent fill evidence"
                        ),
                    }
                )
        final_snapshot = portfolio.snapshot(last_event.receive_time_ns)
        if not checkpoint_mode and (
            not equity_curve
            or equity_curve[-1]["event_time_ns"]
            != final_snapshot["event_time_ns"]
            or equity_curve[-1]["equity"] != final_snapshot["equity"]
        ):
            equity_curve.append(final_snapshot)
        checkpoint_document = (
            {
                "schema_version": 1,
                "event_offset": event_offset + processed,
                "portfolio": portfolio.export_state(),
                "pending": [
                    {
                        "intent_id": intent.intent_id,
                        "instrument_id": intent.instrument_id,
                        "side": intent.side,
                        "quantity": format(intent.quantity, "f"),
                        "decision_time_ns": intent.decision_time_ns,
                        "intent_type": intent.intent_type,
                        "limit_price": (
                            format(intent.limit_price, "f")
                            if intent.limit_price is not None
                            else None
                        ),
                        "latest_outcome_reason": pending_reasons.get(
                            intent.intent_id, ""
                        ),
                    }
                    for intent in pending
                ],
                "intent_ids": sorted(intent_ids),
                "signals": signals,
                "costs": {
                    name: format(value, "f")
                    for name, value in sorted(costs.items())
                },
                "last_event_key": list(previous_key or ()),
                "last_receive_time_ns": previous_receive_time_ns,
                "last_ingest_id": previous_ingest_id,
                "equity_curve": equity_curve,
            }
            if checkpoint_mode
            else None
        )
        return RunnerResult(
            strategy_id=strategy.strategy_id,
            events_processed=processed,
            signals=signals,
            intents=all_intents,
            fills=fills,
            rejected=rejected,
            missed=missed,
            equity_curve=equity_curve,
            cost_components=costs,
            final_snapshot=final_snapshot,
            diagnostics={
                "fill_model_promotion_eligible": self.fill_model.promotion_eligible,
                "promotion_eligible": self.fill_model.promotion_eligible
                and all(Decimal(row["equity"]) > 0 for row in equity_curve),
                "rejected_intents": len(rejected),
                "missed_intents": len(missed),
                "missed_fill_opportunity_cost": "not estimated",
                "lifecycle_events": lifecycle_events,
                "equity_sampling_interval": self.equity_sampling_interval,
                "streaming_replay": True,
                "instrument_multipliers": dict(portfolio.instrument_multipliers),
            },
            checkpoint=checkpoint_document,
        )

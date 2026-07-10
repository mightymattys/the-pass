"""Minimal deterministic event simulator for replay and paper parity."""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from the_pass.data.contracts import CanonicalEvent, EventType

from .contracts import CostModel, FillModel, RiskPolicy, RunnerContext, RunnerResult, SimulatedIntent, StrategyRunner
from .portfolio import AccountingPortfolio


class AllowAllRiskPolicy:
    def allow(self, intent: SimulatedIntent, portfolio: AccountingPortfolio) -> tuple[bool, str]:
        return True, ""


class EventSimulator:
    def __init__(
        self,
        *,
        fill_model: FillModel,
        cost_model: CostModel,
        initial_cash: Decimal = Decimal("100000"),
        risk_policy: RiskPolicy | None = None,
    ) -> None:
        self.fill_model = fill_model
        self.cost_model = cost_model
        self.initial_cash = initial_cash
        self.risk_policy = risk_policy or AllowAllRiskPolicy()

    def run(self, strategy: StrategyRunner, events: Iterable[CanonicalEvent]) -> RunnerResult:
        ordered = sorted(events, key=CanonicalEvent.sort_key)
        if not ordered:
            raise ValueError("event simulator requires events")
        portfolio = AccountingPortfolio(self.initial_cash)
        pending: list[SimulatedIntent] = []
        all_intents: list[SimulatedIntent] = []
        fills = []
        rejected: list[dict[str, object]] = []
        missed: list[dict[str, object]] = []
        equity_curve: list[dict[str, object]] = []
        costs = {name: Decimal(0) for name in ("fees", "spread", "slippage", "funding", "borrow", "roll", "rejects_or_missed_fills")}
        signals = 0

        for index, event in enumerate(ordered):
            still_pending = []
            for intent in pending:
                outcome = self.fill_model.evaluate(intent, event, self.cost_model)
                for fill in outcome.fills:
                    portfolio.apply_fill(fill)
                    fills.append(fill)
                    costs["fees"] += fill.fee
                    costs["spread"] += fill.spread_cost
                    costs["slippage"] += fill.slippage_cost
                if outcome.status in {"rejected", "partial_rejected"}:
                    rejected.append({"intent_id": intent.intent_id, "quantity": outcome.remaining_quantity, "reason": outcome.reason})
                elif outcome.status == "missed":
                    missed.append({"intent_id": intent.intent_id, "quantity": outcome.remaining_quantity, "reason": outcome.reason})
                elif outcome.remaining_quantity > 0:
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
            pending = still_pending

            mark_value = event.payload.get("close", event.payload.get("price"))
            if mark_value is not None and event.event_type in {EventType.BAR, EventType.TRADE}:
                equity_curve.append(portfolio.mark(event.instrument_id, Decimal(str(mark_value)), event.receive_time_ns))

            context = RunnerContext(
                event_index=index,
                total_events=len(ordered),
                decision_time_ns=event.receive_time_ns,
                positions=portfolio.positions,
                marks=dict(portfolio.marks),
            )
            new_intents = list(strategy.on_event(event, context))
            signals += len(new_intents)
            for intent in new_intents:
                if intent.decision_time_ns != event.receive_time_ns:
                    raise ValueError("strategy intent decision time must equal current receive time")
                allowed, reason = self.risk_policy.allow(intent, portfolio)
                if not allowed:
                    rejected.append({"intent_id": intent.intent_id, "quantity": intent.quantity, "reason": reason})
                    continue
                pending.append(intent)
                all_intents.append(intent)

        for intent in pending:
            missed.append({"intent_id": intent.intent_id, "quantity": intent.quantity, "reason": "no subsequent fill evidence"})
        final_snapshot = portfolio.snapshot(ordered[-1].receive_time_ns)
        return RunnerResult(
            strategy_id=strategy.strategy_id,
            events_processed=len(ordered),
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
                "rejected_intents": len(rejected),
                "missed_intents": len(missed),
                "missed_fill_opportunity_cost": "not estimated",
            },
        )

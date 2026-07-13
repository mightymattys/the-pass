"""Minimal trusted local strategy used by the offline quick start."""

from decimal import Decimal

from the_pass.engine.contracts import SimulatedIntent


class ExampleThresholdStrategy:
    def __init__(self, threshold: str, strategy_id: str = "example_futures_threshold_v1") -> None:
        self.strategy_id = strategy_id
        self.threshold = Decimal(threshold)

    def on_event(self, event, context):
        if context.event_index != 0 or Decimal(str(event.payload["close"])) <= self.threshold:
            return []
        return [
            SimulatedIntent(
                intent_id="example-entry-1",
                instrument_id=event.instrument_id,
                side="buy",
                quantity=Decimal("1"),
                decision_time_ns=context.decision_time_ns,
                intent_type="bar",
            )
        ]


def build_strategy(config):
    return ExampleThresholdStrategy(
        config["threshold"],
        config.get("strategy_id", "example_futures_threshold_v1"),
    )

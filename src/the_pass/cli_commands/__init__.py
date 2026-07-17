"""CLI command dispatch table."""

from .analysis import (
    handle_audit,
    handle_candidate,
    handle_paper,
    handle_risk,
    handle_robustness,
)
from .control import handle_gate, handle_incident, handle_receipts, handle_workflow
from .operations import (
    handle_agents,
    handle_automation,
    handle_report_dashboard,
    handle_research,
)
from .research import (
    handle_backtest,
    handle_data,
    handle_features,
    handle_screen,
    handle_validate,
    handle_validate_package,
)

COMMAND_HANDLERS = {
    "validate": handle_validate,
    "validate-package": handle_validate_package,
    "data": handle_data,
    "features": handle_features,
    "screen": handle_screen,
    "backtest": handle_backtest,
    "audit": handle_audit,
    "robustness": handle_robustness,
    "risk": handle_risk,
    "candidate": handle_candidate,
    "paper": handle_paper,
    "research": handle_research,
    "automation": handle_automation,
    "agents": handle_agents,
    "report": handle_report_dashboard,
    "dashboard": handle_report_dashboard,
    "incident": handle_incident,
    "workflow": handle_workflow,
    "gate": handle_gate,
    "receipts": handle_receipts,
}

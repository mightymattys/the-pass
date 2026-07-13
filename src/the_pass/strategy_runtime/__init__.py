"""Public custom strategy runtime API."""

from __future__ import annotations

from importlib import import_module
from typing import Any


__all__ = [
    "ExecutionConfig",
    "StrategyDescriptor",
    "StrategyRuntimeError",
    "load_execution_config",
    "load_strategy_descriptor",
    "load_strategy_factory",
    "parse_execution_config",
    "parse_strategy_descriptor",
    "resolve_workspace_path",
    "run_strategy",
    "run_strategy_verified",
    "runner_result_from_document",
]


_EXPORT_MODULES = {
    "ExecutionConfig": ".config",
    "StrategyDescriptor": ".config",
    "StrategyRuntimeError": ".runtime",
    "load_execution_config": ".config",
    "load_strategy_descriptor": ".config",
    "load_strategy_factory": ".loader",
    "parse_execution_config": ".config",
    "parse_strategy_descriptor": ".config",
    "resolve_workspace_path": ".paths",
    "run_strategy": ".runtime",
    "run_strategy_verified": ".runtime",
    "runner_result_from_document": ".runtime",
}


def __getattr__(name: str) -> Any:
    module_name = _EXPORT_MODULES.get(name)
    if module_name is None:
        raise AttributeError(name)
    value = getattr(import_module(module_name, __name__), name)
    globals()[name] = value
    return value

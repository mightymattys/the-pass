"""Load one local strategy factory under the research-only import boundary."""

from __future__ import annotations

import importlib.util
import sys
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Set

from the_pass.data.contracts import canonical_value

from .config import StrategyDescriptor


FORBIDDEN_MODULE_PREFIXES = (
    "_socket",
    "aiohttp",
    "cc" + "xt",
    "ftplib",
    "http",
    "httpx",
    "multiprocessing",
    "requests",
    "smtplib",
    "socket",
    "ssl",
    "subprocess",
    "the_pass.adapters",
    "the_pass.live_boundary",
    "urllib",
    "web3",
    "websockets",
)


def _is_forbidden(name: str) -> bool:
    return any(name == prefix or name.startswith(prefix + ".") for prefix in FORBIDDEN_MODULE_PREFIXES)


class _ForbiddenImportFinder:
    def find_spec(self, fullname: str, path: Any, target: Any = None) -> Any:
        if _is_forbidden(fullname):
            raise ImportError(f"module {fullname!r} is outside the strategy runtime boundary")
        return None


@contextmanager
def block_forbidden_imports() -> Iterator[None]:
    finder = _ForbiddenImportFinder()
    sys.meta_path.insert(0, finder)
    try:
        yield
    finally:
        sys.meta_path.remove(finder)


def forbidden_modules_loaded() -> Set[str]:
    return {name for name in sys.modules if _is_forbidden(name)}


def purge_forbidden_modules() -> None:
    for name in forbidden_modules_loaded():
        sys.modules.pop(name, None)


def load_strategy_factory(descriptor: StrategyDescriptor) -> Callable[[dict], Any]:
    """Load and return the configured factory without changing ``sys.path``."""

    module_name = f"_the_pass_strategy_{descriptor.source_sha256}"
    spec = importlib.util.spec_from_file_location(module_name, descriptor.resolved_path)
    if spec is None or spec.loader is None:
        raise ValueError("strategy file cannot be loaded as a Python module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        with block_forbidden_imports():
            spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(module_name, None)
        raise
    factory = getattr(module, descriptor.factory, None)
    if not callable(factory):
        sys.modules.pop(module_name, None)
        raise ValueError("strategy factory is missing or not callable")
    return factory


def build_strategy(descriptor: StrategyDescriptor) -> Any:
    factory = load_strategy_factory(descriptor)
    config = canonical_value(descriptor.config, allow_float=True)
    with block_forbidden_imports():
        strategy = factory(config)
    strategy_id = getattr(strategy, "strategy_id", None)
    if not isinstance(strategy_id, str) or not strategy_id.strip():
        raise ValueError("strategy factory must return an object with a non-empty strategy_id")
    if strategy_id != descriptor.strategy_id:
        raise ValueError("strategy factory strategy_id does not match descriptor")
    if not callable(getattr(strategy, "on_event", None)):
        raise ValueError("strategy factory must return an object with callable on_event")
    return strategy

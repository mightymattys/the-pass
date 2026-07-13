"""Versioned custom strategy descriptor and execution configuration."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Mapping, Union

from the_pass.data.contracts import canonical_value, decimal_string, stable_fingerprint
from the_pass.safety import contains_sensitive_key

from .paths import PathLike, resolve_workspace_path


RUNTIME_VERSION = "strategy-runtime-v1"
ASSET_CLASSES = {"crypto_spot", "futures", "prediction_market"}
FILL_MODELS = {
    "bar_next_open",
    "market_depth",
    "limit_evidence",
    "diagnostic_midpoint",
}
PROMOTION_ELIGIBLE_FILL_MODELS = {
    "bar_next_open",
    "market_depth",
    "limit_evidence",
}


def _reject_constant(value: str) -> None:
    raise ValueError("JSON numeric values must be finite")


def _unique_object(pairs: list) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("JSON objects must not contain duplicate keys")
        result[key] = value
    return result


def load_json_object(path: PathLike, *, label: str) -> Dict[str, Any]:
    try:
        value = json.loads(
            Path(path).read_text(encoding="utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_object,
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} must be valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _require_exact_keys(
    document: Mapping[str, Any],
    *,
    required: set,
    optional: set,
    label: str,
) -> None:
    keys = set(document)
    missing = required - keys
    unknown = keys - required - optional
    if missing:
        raise ValueError(f"{label} missing required fields: {', '.join(sorted(missing))}")
    if unknown:
        raise ValueError(f"{label} contains unknown fields: {', '.join(sorted(unknown))}")


def _non_empty_string(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _decimal_string(value: Any, *, field: str, positive: bool = False) -> Decimal:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a decimal string")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a decimal string") from exc
    if not number.is_finite() or number < 0 or (positive and number == 0):
        qualifier = "positive" if positive else "non-negative"
        raise ValueError(f"{field} must be finite and {qualifier}")
    return number


@dataclass(frozen=True)
class StrategyDescriptor:
    schema_version: int
    strategy_id: str
    strategy_file: str
    factory: str
    config: Mapping[str, Any]
    asset_class: str
    owner: str
    workspace_root: Path
    resolved_path: Path
    source_sha256: str
    config_fingerprint: str
    descriptor_fingerprint: str
    runtime_version: str = RUNTIME_VERSION

    def input_document(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "strategy_id": self.strategy_id,
            "strategy_file": self.strategy_file,
            "factory": self.factory,
            "config": canonical_value(self.config, allow_float=True),
            "asset_class": self.asset_class,
            "owner": self.owner,
        }

    def as_dict(self) -> Dict[str, Any]:
        return {
            **self.input_document(),
            "resolved_path": str(self.resolved_path),
            "source_sha256": self.source_sha256,
            "config_fingerprint": self.config_fingerprint,
            "descriptor_fingerprint": self.descriptor_fingerprint,
            "runtime_version": self.runtime_version,
        }


@dataclass(frozen=True)
class ExecutionConfig:
    schema_version: int
    initial_cash: Decimal
    fill_model: str
    fee_rate: Decimal
    slippage_bps: Decimal
    queue_haircut: Decimal
    adverse_selection_haircut: Decimal
    promotion_eligible: bool
    fingerprint: str

    def input_document(self) -> Dict[str, Any]:
        document = {
            "schema_version": self.schema_version,
            "initial_cash": decimal_string(self.initial_cash),
            "fill_model": self.fill_model,
            "fee_rate": decimal_string(self.fee_rate),
            "slippage_bps": decimal_string(self.slippage_bps),
        }
        if self.fill_model == "limit_evidence":
            document.update(
                {
                    "queue_haircut": decimal_string(self.queue_haircut),
                    "adverse_selection_haircut": decimal_string(
                        self.adverse_selection_haircut
                    ),
                }
            )
        return document

    def as_dict(self) -> Dict[str, Any]:
        return {
            **self.input_document(),
            "promotion_eligible": self.promotion_eligible,
            "fingerprint": self.fingerprint,
        }


def parse_strategy_descriptor(
    document: Mapping[str, Any], *, workspace_root: PathLike
) -> StrategyDescriptor:
    if not isinstance(document, Mapping):
        raise ValueError("strategy descriptor must be a JSON object")
    _require_exact_keys(
        document,
        required={
            "schema_version",
            "strategy_id",
            "strategy_file",
            "config",
            "asset_class",
            "owner",
        },
        optional={"factory"},
        label="strategy descriptor",
    )
    if document["schema_version"] != 1 or isinstance(document["schema_version"], bool):
        raise ValueError("strategy descriptor schema_version must be 1")

    strategy_id = _non_empty_string(document["strategy_id"], field="strategy_id")
    strategy_file = _non_empty_string(document["strategy_file"], field="strategy_file")
    factory = _non_empty_string(document.get("factory", "build_strategy"), field="factory")
    if not factory.isidentifier():
        raise ValueError("factory must be a Python identifier")
    config = document["config"]
    if not isinstance(config, Mapping):
        raise ValueError("config must be a JSON object")
    if contains_sensitive_key(config):
        raise ValueError("config must not contain credential-like keys")
    try:
        normalized_config = canonical_value(config, allow_float=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("config must contain finite JSON values") from exc
    asset_class = _non_empty_string(document["asset_class"], field="asset_class")
    if asset_class not in ASSET_CLASSES:
        raise ValueError("asset_class is not supported")
    owner = _non_empty_string(document["owner"], field="owner")

    root = Path(workspace_root).expanduser().resolve(strict=True)
    resolved = resolve_workspace_path(root, strategy_file)
    source_sha256 = hashlib.sha256(resolved.read_bytes()).hexdigest()
    core = {
        "schema_version": 1,
        "strategy_id": strategy_id,
        "strategy_file": strategy_file,
        "factory": factory,
        "config": normalized_config,
        "asset_class": asset_class,
        "owner": owner,
    }
    return StrategyDescriptor(
        schema_version=1,
        strategy_id=strategy_id,
        strategy_file=strategy_file,
        factory=factory,
        config=normalized_config,
        asset_class=asset_class,
        owner=owner,
        workspace_root=root,
        resolved_path=resolved,
        source_sha256=source_sha256,
        config_fingerprint=stable_fingerprint(normalized_config),
        descriptor_fingerprint=stable_fingerprint(core),
    )


def load_strategy_descriptor(path: PathLike, *, workspace_root: PathLike) -> StrategyDescriptor:
    return parse_strategy_descriptor(
        load_json_object(path, label="strategy descriptor"),
        workspace_root=workspace_root,
    )


def parse_execution_config(document: Mapping[str, Any]) -> ExecutionConfig:
    if not isinstance(document, Mapping):
        raise ValueError("execution config must be a JSON object")
    optional = {"queue_haircut", "adverse_selection_haircut"}
    _require_exact_keys(
        document,
        required={
            "schema_version",
            "initial_cash",
            "fill_model",
            "fee_rate",
            "slippage_bps",
        },
        optional=optional,
        label="execution config",
    )
    if document["schema_version"] != 1 or isinstance(document["schema_version"], bool):
        raise ValueError("execution config schema_version must be 1")
    fill_model = _non_empty_string(document["fill_model"], field="fill_model")
    if fill_model not in FILL_MODELS:
        raise ValueError("fill_model is not supported")
    supplied_haircuts = optional.intersection(document)
    if supplied_haircuts and fill_model != "limit_evidence":
        raise ValueError("fill haircuts are valid only for limit_evidence")

    initial_cash = _decimal_string(document["initial_cash"], field="initial_cash", positive=True)
    fee_rate = _decimal_string(document["fee_rate"], field="fee_rate")
    slippage_bps = _decimal_string(document["slippage_bps"], field="slippage_bps")
    queue_haircut = _decimal_string(
        document.get("queue_haircut", "0.5"), field="queue_haircut"
    )
    adverse_selection_haircut = _decimal_string(
        document.get("adverse_selection_haircut", "0.75"),
        field="adverse_selection_haircut",
    )
    if queue_haircut > 1 or adverse_selection_haircut > 1:
        raise ValueError("fill haircuts must be between zero and one")

    core = {
        "schema_version": 1,
        "initial_cash": decimal_string(initial_cash),
        "fill_model": fill_model,
        "fee_rate": decimal_string(fee_rate),
        "slippage_bps": decimal_string(slippage_bps),
    }
    if fill_model == "limit_evidence":
        core.update(
            {
                "queue_haircut": decimal_string(queue_haircut),
                "adverse_selection_haircut": decimal_string(adverse_selection_haircut),
            }
        )
    return ExecutionConfig(
        schema_version=1,
        initial_cash=initial_cash,
        fill_model=fill_model,
        fee_rate=fee_rate,
        slippage_bps=slippage_bps,
        queue_haircut=queue_haircut,
        adverse_selection_haircut=adverse_selection_haircut,
        promotion_eligible=fill_model in PROMOTION_ELIGIBLE_FILL_MODELS,
        fingerprint=stable_fingerprint(core),
    )


def load_execution_config(path: PathLike) -> ExecutionConfig:
    return parse_execution_config(load_json_object(path, label="execution config"))


DescriptorInput = Union[StrategyDescriptor, Mapping[str, Any], Path]
ExecutionInput = Union[ExecutionConfig, Mapping[str, Any], Path]

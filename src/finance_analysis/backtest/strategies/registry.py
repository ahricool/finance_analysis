"""Small explicit registry for supported backtest strategies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class StrategyParameterDefinition:
    key: str
    name: str
    type: str
    default: int
    minimum: int
    maximum: int


@dataclass(frozen=True)
class StrategyDefinition:
    key: str
    name: str
    description: str
    version: str
    frequency: str
    supported_markets: tuple[str, ...]
    supported_engines: tuple[str, ...]
    parameters: tuple[StrategyParameterDefinition, ...]

    def validate_parameters(self, values: dict[str, Any] | None) -> dict[str, int]:
        supplied = values or {}
        unknown = set(supplied) - {item.key for item in self.parameters}
        if unknown:
            raise ValueError(f"Unsupported strategy parameters: {', '.join(sorted(unknown))}")
        result: dict[str, int] = {}
        for item in self.parameters:
            value = supplied.get(item.key, item.default)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{item.key} must be an integer")
            if value < item.minimum or value > item.maximum:
                raise ValueError(f"{item.key} must be between {item.minimum} and {item.maximum}")
            result[item.key] = value
        if result["fast_window"] >= result["slow_window"]:
            raise ValueError("fast_window must be less than slow_window")
        return result


SMA_CROSS = StrategyDefinition(
    key="sma_cross",
    name="双均线策略",
    description="收盘后计算简单移动平均线交叉，并在下一交易日开盘调仓。",
    version="1.0.0",
    frequency="1d",
    supported_markets=("US", "CN"),
    supported_engines=("backtrader", "rqalpha"),
    parameters=(
        StrategyParameterDefinition("fast_window", "快均线周期", "integer", 5, 2, 120),
        StrategyParameterDefinition("slow_window", "慢均线周期", "integer", 20, 3, 250),
    ),
)

_STRATEGIES = {SMA_CROSS.key: SMA_CROSS}


def get_strategy(key: str) -> StrategyDefinition:
    try:
        return _STRATEGIES[key]
    except KeyError as exc:
        raise ValueError(f"Unsupported strategy: {key}") from exc


def list_strategies(*, engine: str | None = None, market: str | None = None) -> list[StrategyDefinition]:
    values = list(_STRATEGIES.values())
    if engine:
        values = [item for item in values if engine in item.supported_engines]
    if market:
        values = [item for item in values if market.upper() in item.supported_markets]
    return values

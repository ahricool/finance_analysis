"""Ordered backtest engine capability registry."""

from __future__ import annotations

from dataclasses import dataclass
import importlib.metadata
from finance_analysis.backtest.types import BacktestEngine


@dataclass(frozen=True)
class BacktestEngineDefinition:
    key: str
    name: str
    description: str
    display_order: int
    is_default: bool
    recommended: bool
    available: bool
    unavailable_reason: str | None
    version: str | None
    supported_markets: tuple[str, ...]
    supported_strategies: tuple[str, ...]


def _availability(package: str) -> tuple[bool, str | None, str | None]:
    try:
        version = importlib.metadata.version(package)
        __import__(package)
        return True, None, version
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}", None


def get_engine_definitions() -> list[BacktestEngineDefinition]:
    backtrader_ok, backtrader_reason, backtrader_version = _availability("backtrader")
    rqalpha_ok, rqalpha_reason, rqalpha_version = _availability("rqalpha")
    return [
        BacktestEngineDefinition(
            key="backtrader",
            name="Backtrader",
            description="通用事件驱动回测引擎，优先用于美股策略。",
            display_order=1,
            is_default=True,
            recommended=True,
            available=backtrader_ok,
            unavailable_reason=backtrader_reason,
            version=backtrader_version,
            supported_markets=("US", "CN"),
            supported_strategies=("sma_cross",),
        ),
        BacktestEngineDefinition(
            key="rqalpha",
            name="RQAlpha",
            description="第二套事件驱动回测引擎，通过 PostgreSQL 自定义数据源用于中国市场验证。",
            display_order=2,
            is_default=False,
            recommended=False,
            available=rqalpha_ok,
            unavailable_reason=rqalpha_reason,
            version=rqalpha_version,
            supported_markets=("CN",),
            supported_strategies=("sma_cross",),
        ),
    ]


def get_engine_definition(key: str) -> BacktestEngineDefinition:
    for item in get_engine_definitions():
        if item.key == key:
            return item
    raise ValueError(f"Unsupported backtest engine: {key}")


def create_engine(key: str) -> BacktestEngine:
    definition = get_engine_definition(key)
    if not definition.available:
        raise RuntimeError(definition.unavailable_reason or f"Engine {key} is unavailable")
    if key == "backtrader":
        from finance_analysis.backtest.engines.backtrader_engine import BacktraderBacktestEngine

        return BacktraderBacktestEngine()
    if key == "rqalpha":
        from finance_analysis.backtest.engines.rqalpha_engine import RQAlphaBacktestEngine

        return RQAlphaBacktestEngine()
    raise ValueError(f"Unsupported backtest engine: {key}")


__all__ = ["BacktestEngineDefinition", "create_engine", "get_engine_definition", "get_engine_definitions"]

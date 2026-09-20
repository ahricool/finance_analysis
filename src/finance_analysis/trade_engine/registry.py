# -*- coding: utf-8 -*-
"""Simple strategy registry. One active Position Strategy per position."""

from ..integrations.market_data.models import Market  # pragma: allowlist secret
from .strategies.cn_position_intraday_v1 import CNPositionIntradayV1  # pragma: allowlist secret
from .strategies.exit_v1 import ExitV1  # pragma: allowlist secret
from .strategies.portfolio_risk_v1 import PortfolioRiskV1  # pragma: allowlist secret
from .strategies.us_position_intraday_v1 import USPositionIntradayV1  # pragma: allowlist secret

DEFAULT_POSITION_STRATEGY = {
    Market.CN: "exit_v1",
    "CN": "exit_v1",
    Market.US: "exit_v1",
    "US": "exit_v1",
}

TRADE_STRATEGIES = {
    Market.CN: (ExitV1(), CNPositionIntradayV1(), PortfolioRiskV1()),
    "CN": (ExitV1(), CNPositionIntradayV1(), PortfolioRiskV1()),
    Market.US: (ExitV1(), USPositionIntradayV1(), PortfolioRiskV1()),
    "US": (ExitV1(), USPositionIntradayV1(), PortfolioRiskV1()),
}


def strategies_for(market: str):
    return TRADE_STRATEGIES[market]


def position_strategies(market: str):
    return tuple(item for item in strategies_for(market) if not isinstance(item, PortfolioRiskV1))


def portfolio_strategies(market: str):
    return tuple(item for item in strategies_for(market) if isinstance(item, PortfolioRiskV1))


def default_position_strategy_key(market: str) -> str:
    return DEFAULT_POSITION_STRATEGY.get(market, "exit_v1")


def resolve_position_strategy(market: str, key: str | None = None):
    wanted = (key or "").strip() or default_position_strategy_key(market)
    by_key = {item.key: item for item in position_strategies(market)}
    return by_key.get(wanted) or by_key.get(default_position_strategy_key(market))

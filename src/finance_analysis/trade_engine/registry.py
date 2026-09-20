# -*- coding: utf-8 -*-
"""Simple strategy registry. Not a plugin framework."""

from ..integrations.market_data.models import Market  # pragma: allowlist secret
from .strategies.cn_position_intraday_v1 import CNPositionIntradayV1  # pragma: allowlist secret
from .strategies.exit_v1 import ExitV1  # pragma: allowlist secret
from .strategies.portfolio_risk_v1 import PortfolioRiskV1  # pragma: allowlist secret
from .strategies.us_position_intraday_v1 import USPositionIntradayV1  # pragma: allowlist secret

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

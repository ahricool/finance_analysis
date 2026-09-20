# -*- coding: utf-8 -*-
"""Simple strategy registry. Not a plugin framework."""

from finance_analysis.integrations.market_data.models import Market  # pragma: allowlist secret
from finance_analysis.trade_engine.strategies.cn_intraday_v1 import CNIntradayV1  # pragma: allowlist secret
from finance_analysis.trade_engine.strategies.exit_v1 import ExitV1  # pragma: allowlist secret
from finance_analysis.trade_engine.strategies.portfolio_risk_v1 import PortfolioRiskV1  # pragma: allowlist secret
from finance_analysis.trade_engine.strategies.us_intraday_v1 import USIntradayV1  # pragma: allowlist secret

TRADE_STRATEGIES = {
    Market.CN: (ExitV1(), CNIntradayV1(), PortfolioRiskV1()),
    "CN": (ExitV1(), CNIntradayV1(), PortfolioRiskV1()),
    Market.US: (ExitV1(), USIntradayV1(), PortfolioRiskV1()),
    "US": (ExitV1(), USIntradayV1(), PortfolioRiskV1()),
}


def strategies_for(market: str):
    return TRADE_STRATEGIES[market]


def position_strategies(market: str):
    return tuple(item for item in strategies_for(market) if not isinstance(item, PortfolioRiskV1))


def portfolio_strategies(market: str):
    return tuple(item for item in strategies_for(market) if isinstance(item, PortfolioRiskV1))

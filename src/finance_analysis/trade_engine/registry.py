# -*- coding: utf-8 -*-
"""Registered Position Strategies run in parallel. Portfolio Risk Facts are separate."""

from .strategies.add_v1 import AddV1  # pragma: allowlist secret
from .strategies.exit_v1 import ExitV1  # pragma: allowlist secret
from .strategies.portfolio_risk_v1 import PortfolioRiskV1  # pragma: allowlist secret

POSITION_STRATEGIES = (ExitV1(), AddV1())
PORTFOLIO_STRATEGIES = (PortfolioRiskV1(),)


def position_strategies(market: str):
    del market
    return POSITION_STRATEGIES


def portfolio_strategies(market: str):
    del market
    return PORTFOLIO_STRATEGIES


def strategies_for(market: str):
    return tuple(position_strategies(market)) + tuple(portfolio_strategies(market))

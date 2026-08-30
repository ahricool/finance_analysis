"""ETF rotation research backtest: T-close signals, T+1 open fills, strategies A-I."""

from finance_analysis.etf_rotation.backtest.runner import run_market
from finance_analysis.etf_rotation.backtest.strategies import STRATEGIES

__all__ = ["STRATEGIES", "run_market"]

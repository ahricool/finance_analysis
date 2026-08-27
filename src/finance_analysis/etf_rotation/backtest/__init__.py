"""A-share ETF rotation backtest: previous-day entry rank, T+1 open, top-2 hold."""

from finance_analysis.etf_rotation.backtest.runner import (
    format_result,
    result_to_dict,
    run_rotation_backtest,
)
from finance_analysis.etf_rotation.backtest.universe import a_share_etfs

__all__ = ["a_share_etfs", "format_result", "result_to_dict", "run_rotation_backtest"]

"""CN ETF rotation backtest: previous-day entry rank, T+1 open, top-2 hold."""

from finance_analysis.etf_rotation.backtest.runner import (
    format_result,
    result_to_dict,
    run_rotation_backtest,
)

__all__ = ["format_result", "result_to_dict", "run_rotation_backtest"]

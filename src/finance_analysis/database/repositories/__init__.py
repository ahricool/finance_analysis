# -*- coding: utf-8 -*-
"""Database repository package."""

__all__ = [
    "AnalysisRepository",
    "BacktestRepository",
    "StockRepository",
    "TaskRecordRepository",
]


def __getattr__(name: str):
    if name == "AnalysisRepository":
        from finance_analysis.database.repositories.analysis import AnalysisRepository

        return AnalysisRepository
    if name == "BacktestRepository":
        from finance_analysis.database.repositories.backtest import BacktestRepository

        return BacktestRepository
    if name == "StockRepository":
        from finance_analysis.database.repositories.stock import StockRepository

        return StockRepository
    if name == "TaskRecordRepository":
        from finance_analysis.database.repositories.task_record import TaskRecordRepository

        return TaskRecordRepository
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

# -*- coding: utf-8 -*-
"""Database repository package with lazy imports to avoid cycles."""

__all__ = [
    "AnalysisRepository",
    "AdjustmentWriteStats",
    "BacktestRepository",
    "MarketDataSymbolRepository",
    "QuantRepository",
    "StockRepository",
    "StockAdjustmentRepository",
    "TaskRecordRepository",
    "UpsertStats",
]


def __getattr__(name: str):
    if name in {"AdjustmentWriteStats", "StockAdjustmentRepository"}:
        from finance_analysis.database.repositories.adjustment import (
            AdjustmentWriteStats,
            StockAdjustmentRepository,
        )

        return {
            "AdjustmentWriteStats": AdjustmentWriteStats,
            "StockAdjustmentRepository": StockAdjustmentRepository,
        }[name]
    if name == "AnalysisRepository":
        from finance_analysis.database.repositories.analysis import AnalysisRepository

        return AnalysisRepository
    if name == "BacktestRepository":
        from finance_analysis.database.repositories.backtest import BacktestRepository

        return BacktestRepository
    if name == "QuantRepository":
        from finance_analysis.database.repositories.quant import QuantRepository

        return QuantRepository
    if name in {"MarketDataSymbolRepository", "StockRepository", "UpsertStats"}:
        from finance_analysis.database.repositories.stock import (
            MarketDataSymbolRepository,
            StockRepository,
            UpsertStats,
        )

        return {
            "MarketDataSymbolRepository": MarketDataSymbolRepository,
            "StockRepository": StockRepository,
            "UpsertStats": UpsertStats,
        }[name]
    if name == "TaskRecordRepository":
        from finance_analysis.database.repositories.task_record import TaskRecordRepository

        return TaskRecordRepository
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

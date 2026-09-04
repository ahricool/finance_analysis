# -*- coding: utf-8 -*-
"""Database repository package with lazy imports to avoid cycles."""

__all__ = [
    "AnalysisRepository",
    "InstrumentRepository",
    "QuantRepository",
    "StockRepository",
    "TaskRecordRepository",
    "UniverseCycleError",
    "UniverseRepository",
    "UniverseResolver",
    "UpsertStats",
]


def __getattr__(name: str):
    if name == "AnalysisRepository":
        from finance_analysis.database.repositories.analysis import AnalysisRepository

        return AnalysisRepository
    if name == "QuantRepository":
        from finance_analysis.database.repositories.quant import QuantRepository

        return QuantRepository
    if name in {"InstrumentRepository", "StockRepository", "UpsertStats"}:
        from finance_analysis.database.repositories.stock import (
            InstrumentRepository,
            StockRepository,
            UpsertStats,
        )

        return {
            "InstrumentRepository": InstrumentRepository,
            "StockRepository": StockRepository,
            "UpsertStats": UpsertStats,
        }[name]
    if name == "TaskRecordRepository":
        from finance_analysis.database.repositories.task_record import TaskRecordRepository

        return TaskRecordRepository
    if name in {"UniverseCycleError", "UniverseRepository", "UniverseResolver"}:
        from finance_analysis.database.repositories.universe import (
            UniverseCycleError,
            UniverseRepository,
            UniverseResolver,
        )

        return {
            "UniverseCycleError": UniverseCycleError,
            "UniverseRepository": UniverseRepository,
            "UniverseResolver": UniverseResolver,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

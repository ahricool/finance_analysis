# -*- coding: utf-8 -*-
"""Stable metadata for on-demand Celery tasks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class CeleryTaskMetadata:
    """Stable identifiers shared by registration and lifecycle tracking."""

    celery_name: str
    task_type: str
    display_name: str
    source: str


DEMO_ADD_TASK = CeleryTaskMetadata(
    celery_name="demo.add",
    task_type="demo_add",
    display_name="Demo Add",
    source="celery",
)
STOCK_ANALYSIS_TASK = CeleryTaskMetadata(
    celery_name="analysis.run_stock_analysis",
    task_type="stock_analysis",
    display_name="股票分析",
    source="celery_manual",
)
MARKET_REVIEW_TASK = CeleryTaskMetadata(
    celery_name="analysis.run_market_review",
    task_type="market_review",
    display_name="大盘复盘",
    source="celery_manual",
)
MARKET_CALENDAR_IMPORTANCE_TASK = CeleryTaskMetadata(
    celery_name="analysis.market_calendar_importance",
    task_type="market_calendar_importance",
    display_name="财经日历重要性评分",
    source="celery",
)
BACKTEST_TASK = CeleryTaskMetadata(
    celery_name="backtest.run",
    task_type="backtest",
    display_name="策略回测",
    source="celery_manual",
)
QUANT_DATASET_TASK = CeleryTaskMetadata(
    celery_name="quant.dataset.build", task_type="quant_dataset", display_name="构建量化数据集", source="celery_manual"
)
QUANT_TRAINING_TASK = CeleryTaskMetadata(
    celery_name="quant.model.train", task_type="quant_training", display_name="训练量化模型", source="celery_manual"
)

ON_DEMAND_TASKS = (
    BACKTEST_TASK,
    DEMO_ADD_TASK,
    STOCK_ANALYSIS_TASK,
    MARKET_REVIEW_TASK,
    MARKET_CALENDAR_IMPORTANCE_TASK,
    QUANT_DATASET_TASK,
    QUANT_TRAINING_TASK,
)
_ON_DEMAND_TASKS_BY_NAME = {item.celery_name: item for item in ON_DEMAND_TASKS}


def get_on_demand_task_metadata(task_name: str) -> Optional[CeleryTaskMetadata]:
    return _ON_DEMAND_TASKS_BY_NAME.get(task_name)


__all__ = [
    "BACKTEST_TASK",
    "CeleryTaskMetadata",
    "DEMO_ADD_TASK",
    "MARKET_CALENDAR_IMPORTANCE_TASK",
    "MARKET_REVIEW_TASK",
    "QUANT_DATASET_TASK",
    "QUANT_TRAINING_TASK",
    "ON_DEMAND_TASKS",
    "STOCK_ANALYSIS_TASK",
    "get_on_demand_task_metadata",
]

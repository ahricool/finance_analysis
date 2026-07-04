"""Closed model runner registry; arbitrary imports and function execution are forbidden."""

from __future__ import annotations

from qlib_worker.models.base import BaseLGBMRunner
from qlib_worker.models.cross_section import CrossSectionLGBMRunner
from qlib_worker.models.time_series import TimeSeriesLGBMRunner

MODEL_RUNNERS: dict[str, type[BaseLGBMRunner]] = {
    "cross_section_lgbm": CrossSectionLGBMRunner,
    "time_series_lgbm": TimeSeriesLGBMRunner,
}


def get_runner(model_key: str) -> BaseLGBMRunner:
    runner = MODEL_RUNNERS.get(model_key)
    if runner is None:
        raise ValueError(f"Unknown model_key: {model_key}")
    return runner()

# -*- coding: utf-8 -*-
"""Backtest-owned configuration."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache


@dataclass
class BacktestConfig:
    backtest_eval_window_days: int = 10
    backtest_min_age_days: int = 14
    backtest_engine_version: str = "v1"
    backtest_neutral_band_pct: float = 2.0


@lru_cache(maxsize=1)
def get_backtest_config() -> BacktestConfig:
    return BacktestConfig()

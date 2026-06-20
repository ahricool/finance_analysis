# -*- coding: utf-8 -*-
"""Backtest-owned configuration."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from src.utils.env import env_bool, env_float, env_int, env_str


@dataclass(frozen=True)
class BacktestConfig:
    backtest_enabled: bool = True
    backtest_eval_window_days: int = 10
    backtest_min_age_days: int = 14
    backtest_engine_version: str = "v1"
    backtest_neutral_band_pct: float = 2.0


@lru_cache(maxsize=1)
def get_backtest_config() -> BacktestConfig:
    return BacktestConfig(
        backtest_enabled=env_bool("BACKTEST_ENABLED", True),
        backtest_eval_window_days=env_int("BACKTEST_EVAL_WINDOW_DAYS", 10, minimum=1),
        backtest_min_age_days=env_int("BACKTEST_MIN_AGE_DAYS", 14, minimum=1),
        backtest_engine_version=env_str("BACKTEST_ENGINE_VERSION", "v1") or "v1",
        backtest_neutral_band_pct=env_float("BACKTEST_NEUTRAL_BAND_PCT", 2.0, minimum=0.0),
    )

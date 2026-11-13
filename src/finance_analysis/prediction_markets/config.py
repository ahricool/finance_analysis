"""Disposable-cache limits."""

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Config:
    live_ttl: int = 60
    history_ttl: int = 300
    stale_seconds: int = 300
    concurrency: int = 4
    latest_tolerance: int = 900
    baseline_tolerance: int = 3600


@lru_cache
def get_config():
    from finance_analysis.config import load_env

    load_env()
    return Config(
        live_ttl=max(10, int(os.getenv("POLYMARKET_LIVE_TTL", "60"))),
        history_ttl=max(60, int(os.getenv("POLYMARKET_HISTORY_TTL", "300"))),
    )

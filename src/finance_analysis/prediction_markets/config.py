"""Opt-in feature and disposable-cache limits."""

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Config:
    enabled: bool = False
    live_ttl: int = 60
    history_ttl: int = 300
    stale_seconds: int = 300
    concurrency: int = 4
    latest_tolerance: int = 900
    baseline_tolerance: int = 3600
    candidate_group_size: int = 8
    focus_symbols: tuple[str, ...] = ()


@lru_cache
def get_config():
    from finance_analysis.config import load_env

    load_env()
    return Config(
        enabled=os.getenv("POLYMARKET_ENABLED", "false").lower() in {"true", "1", "yes"},
        live_ttl=max(10, int(os.getenv("POLYMARKET_LIVE_TTL", "60"))),
        history_ttl=max(60, int(os.getenv("POLYMARKET_HISTORY_TTL", "300"))),
        focus_symbols=tuple(
            sorted(set(s.strip().upper() for s in os.getenv("POLYMARKET_FOCUS_SYMBOLS", "").split(",") if s.strip()))
        ),
    )

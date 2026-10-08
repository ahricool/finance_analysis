"""Versioned, configurable initial rules; historical evidence remains separate."""

from dataclasses import dataclass
from functools import lru_cache
import os
import math


@dataclass(frozen=True)
class OptionsConfig:
    enabled: bool = True
    feed: str = "indicative"
    max_dte: int = 90
    max_expirations: int = 12
    max_contracts: int = 2500
    min_moneyness: float = 0.7
    max_moneyness: float = 1.3
    cache_seconds: int = 900
    quote_max_age: int = 300
    timestamp_tolerance: int = 120
    daily_iv_max_age: int = 14400
    min_iv: float = 0.01
    max_iv: float = 5.0
    atm_moneyness_tolerance: float = 0.05
    min_volume: int = 100
    min_oi: int = 100
    min_history_days: int = 20
    history_days: int = 120
    volume_oi_alert: float = 3.0
    premium_alert: float = 1_000_000
    percentile_alert: float = 95.0
    skew_alert: float = 0.08
    skew_change_alert: float = 0.03
    term_inversion_alert: float = 0.05
    oi_change_alert: int = 100
    oi_growth_alert: float = 0.2
    low_premium: float = 0.1
    near_expiry_days: int = 7
    spread_base: float = 0.08
    spread_floor_dollars: float = 0.05
    low_depth: int = 10
    deep_otm_call: float = 1.15
    deep_otm_put: float = 0.85
    near_expiry_spread_factor: float = 1.5
    liquidity_alert: float = 80.0
    wide_spread_factor: float = 2.0
    activity_rule_level: float = 75.0
    skew_tenor_tolerance: float = 0.25
    put_iv_min_moneyness: float = 0.9
    put_iv_max_moneyness: float = 1.03
    llm_score: float = 85.0
    auto_explain: bool = False
    default_symbols: tuple[str, ...] = ("SPY.US", "QQQ.US", "NVDA.US", "AAPL.US", "MSFT.US", "TSLA.US")
    # Evidence weights are normalized over available inputs, never across the three scores.
    corroboration_increment: float = 25.0
    activity_weights: tuple[float, ...] = (0.45, 0.2, 0.15, 0.1, 0.1)
    bearish_weights: tuple[float, ...] = (0.25, 0.15, 0.25, 0.15, 0.1, 0.1)
    liquidity_weights: tuple[float, ...] = (0.45, 0.1, 0.15, 0.15, 0.15)
    rule_version: str = "options-v1"


@lru_cache(maxsize=1)
def get_options_config() -> OptionsConfig:
    from finance_analysis.config import load_env

    load_env()
    values = {}
    defaults = OptionsConfig()
    for key in defaults.__dataclass_fields__:
        name = f"OPTIONS_{key.upper()}"
        if name not in os.environ or isinstance(getattr(defaults, key), tuple):
            continue
        raw, default = os.environ[name], getattr(defaults, key)
        values[key] = raw.lower() in {"1", "true", "yes"} if isinstance(default, bool) else type(default)(raw)
    result = OptionsConfig(**values)
    if result.feed not in {"indicative", "opra"}:
        raise ValueError("OPTIONS_FEED must be indicative or opra")
    if not (
        0 < result.min_moneyness < result.max_moneyness
        and result.min_history_days >= 2
        and result.max_dte > 0
        and result.max_expirations > 0
        and result.max_contracts > 0
        and result.cache_seconds > 0
        and result.quote_max_age > 0
    ):
        raise ValueError("Invalid Options Intelligence limits")
    if (
        any(isinstance(value, float) and (not math.isfinite(value) or value <= 0) for value in result.__dict__.values())
        or result.min_volume <= 0
        or result.min_oi <= 0
    ):
        raise ValueError("Options numeric rules must be positive and finite")
    return result

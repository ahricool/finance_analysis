# -*- coding: utf-8 -*-
"""V1 portfolio-risk policy. Parameters are unverified and must not be tuned here."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from functools import lru_cache
from typing import Literal

from finance_analysis.config.env_parsing import env_str  # pragma: allowlist secret

RULE_VERSION = "exit_v1"
VWAPMode = Literal["exact_or_proxy", "exact_only"]


@dataclass(frozen=True, slots=True)
class RiskPolicy:
    max_symbol_weight: Decimal = Decimal("0.10")
    risk_per_symbol: Decimal = Decimal("0.005")
    total_open_risk: Decimal = Decimal("0.02")
    max_gross_exposure: Decimal = Decimal("0.50")
    vwap_mode: VWAPMode = "exact_or_proxy"
    rvol_weak: Decimal = Decimal("1.3")
    rvol_severe: Decimal = Decimal("1.5")
    stage_a_max: Decimal = Decimal("0.05")
    stage_b_max: Decimal = Decimal("0.15")
    capital_stop: Decimal = Decimal("0.04")
    stage_b_lock: Decimal = Decimal("0.35")
    stage_c_lock: Decimal = Decimal("0.60")
    ema_period: int = 20
    ema_warmup: int = 60
    structure_bars: int = 6
    rvol_days: int = 10
    quote_max_age_seconds: int = 90
    five_minute_timeout_seconds: int = 20
    quote_timeout_seconds: int = 5
    max_symbol_concurrency: int = 4
    publish_buffer_seconds: int = 20
    min_profit_to_add: Decimal = Decimal("0.03")
    max_add_count: int = 1
    max_extension_atr: Decimal = Decimal("1.5")
    min_stop_distance_atr: Decimal = Decimal("0.75")
    max_stop_atr: Decimal = Decimal("2")
    max_add_value_fraction: Decimal = Decimal("0.30")
    min_breakout_volume_ratio: Decimal = Decimal("1.2")
    pullback_high_min: Decimal = Decimal("0.05")
    consolidation_min_days: int = 3
    consolidation_max_days: int = 8
    pullback_min_days: int = 2
    pullback_max_days: int = 5
    add_ma_fast: int = 10
    add_ma_slow: int = 20
    atr_period: int = 14
    daily_lookback_days: int = 80
    rule_version: str = RULE_VERSION

    def merge(self, payload: dict | None) -> "RiskPolicy":
        if not payload:
            return self
        data = {}
        for key in (
            "max_symbol_weight",
            "risk_per_symbol",
            "total_open_risk",
            "max_gross_exposure",
            "vwap_mode",
            "min_profit_to_add",
            "max_extension_atr",
            "min_stop_distance_atr",
            "max_stop_atr",
            "max_add_value_fraction",
        ):
            if key in payload and payload[key] is not None:
                data[key] = Decimal(str(payload[key])) if key != "vwap_mode" else str(payload[key])
        return replace(self, **data)


@lru_cache(maxsize=1)
def get_risk_policy() -> RiskPolicy:
    mode = (env_str("PORTFOLIO_RISK_VWAP_MODE", "exact_or_proxy") or "exact_or_proxy").strip()
    if mode not in {"exact_or_proxy", "exact_only"}:
        mode = "exact_or_proxy"
    return RiskPolicy(vwap_mode=mode)


def reset_risk_policy() -> None:
    get_risk_policy.cache_clear()

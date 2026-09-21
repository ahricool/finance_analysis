# -*- coding: utf-8 -*-
"""V1 portfolio-risk policy. Parameters are unverified and must not be tuned here."""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from functools import lru_cache

RULE_VERSION = "exit_v1"


@dataclass(frozen=True, slots=True)
class RiskPolicy:
    max_symbol_weight: Decimal = Decimal("0.10")
    risk_per_symbol: Decimal = Decimal("0.005")
    total_open_risk: Decimal = Decimal("0.02")
    max_gross_exposure: Decimal = Decimal("0.50")
    stage_a_max: Decimal = Decimal("0.05")
    stage_b_max: Decimal = Decimal("0.15")
    capital_stop: Decimal = Decimal("0.04")
    stage_b_lock: Decimal = Decimal("0.35")
    stage_c_lock: Decimal = Decimal("0.60")
    structure_bars: int = 6
    quote_max_age_seconds: int = 90
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
            "min_profit_to_add",
            "max_extension_atr",
            "min_stop_distance_atr",
            "max_stop_atr",
            "max_add_value_fraction",
        ):
            if key in payload and payload[key] is not None:
                data[key] = Decimal(str(payload[key]))
        return replace(self, **data)


@lru_cache(maxsize=1)
def get_risk_policy() -> RiskPolicy:
    return RiskPolicy()


def reset_risk_policy() -> None:
    get_risk_policy.cache_clear()

# -*- coding: utf-8 -*-
"""Market review configuration."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache


@dataclass
class MarketReviewConfig:
    market_review_region: str = "cn"
    trading_day_check_enabled: bool = True


@lru_cache(maxsize=1)
def get_market_review_config() -> MarketReviewConfig:
    return MarketReviewConfig()

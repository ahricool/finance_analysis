"""Configuration needed by market reviews and their news/LLM adapters."""

from dataclasses import dataclass
from functools import lru_cache

from finance_analysis.llm.config import LLMConfig, get_llm_config
from finance_analysis.market_review.config import get_market_review_config
from finance_analysis.reporting.config import get_report_config


@dataclass(frozen=True)
class MarketReviewRuntimeConfig:
    llm: LLMConfig
    report_language: str
    market_review_region: str
    trading_day_check_enabled: bool


@lru_cache(maxsize=1)
def get_market_review_runtime_config() -> MarketReviewRuntimeConfig:
    review = get_market_review_config()
    return MarketReviewRuntimeConfig(
        llm=get_llm_config(),
        report_language=get_report_config().report_language,
        market_review_region=review.market_review_region,
        trading_day_check_enabled=review.trading_day_check_enabled,
    )

# -*- coding: utf-8 -*-
"""Market intelligence service configuration."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from finance_analysis.config.env_parsing import env_str


@dataclass
class SocialSentimentConfig:
    social_sentiment_api_key: str | None = None
    social_sentiment_api_url: str = "https://api.adanos.org"


@lru_cache(maxsize=1)
def get_social_sentiment_config() -> SocialSentimentConfig:
    return SocialSentimentConfig(
        social_sentiment_api_key=env_str("SOCIAL_SENTIMENT_API_KEY") or None,
        social_sentiment_api_url=(
            env_str("SOCIAL_SENTIMENT_API_URL", "https://api.adanos.org") or "https://api.adanos.org"
        ).rstrip("/"),
    )

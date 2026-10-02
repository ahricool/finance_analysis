"""Explicit earnings-only policy and cost controls."""

import os
from dataclasses import dataclass

PROMPT_VERSION = "earnings-v1"
UNIVERSES = ("us_sp500", "us_nasdaq100")


@dataclass(frozen=True)
class OutlookConfig:
    research_ttl_hours: int = 24
    concurrency: int = 2
    lookahead_days: int = 7
    eps_relative_tolerance: float = 0.02
    eps_absolute_usd: float = 0.01
    revenue_relative_tolerance: float = 0.01

    @classmethod
    def from_env(cls):
        values = {k: type(v)(os.getenv("EARNINGS_OUTLOOK_" + k.upper(), v)) for k, v in vars(cls()).items()}
        config = cls(**values)
        if not (
            1 <= config.concurrency <= 8 and 1 <= config.lookahead_days <= 30 and 1 <= config.research_ttl_hours <= 168
        ):
            raise ValueError("Invalid earnings outlook TTL/concurrency/window")
        if any(
            not 0 <= v <= 1
            for v in (config.eps_relative_tolerance, config.eps_absolute_usd, config.revenue_relative_tolerance)
        ):
            raise ValueError("Invalid earnings meet tolerance")
        return config

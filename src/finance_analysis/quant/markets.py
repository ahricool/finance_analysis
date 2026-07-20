"""Market-specific quantitative research configuration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time


@dataclass(frozen=True)
class QuantMarketConfig:
    market: str
    timezone: str
    market_close_time: time
    market_open_time: time
    default_universe: str
    primary_benchmark: str
    broad_benchmark: str
    risk_benchmark: str

    @property
    def calendar_market(self) -> str:
        return self.market.lower()

    @property
    def benchmark_dependencies(self) -> frozenset[str]:
        return frozenset((self.primary_benchmark, self.broad_benchmark, self.risk_benchmark))


QUANT_MARKETS = {
    "US": QuantMarketConfig(
        market="US",
        timezone="America/New_York",
        market_close_time=time(16, 0),
        market_open_time=time(9, 30),
        default_universe="us_sp500_watchlist",
        primary_benchmark="QQQ.US",
        broad_benchmark="SPY.US",
        risk_benchmark="SOXX.US",
    ),
    "CN": QuantMarketConfig(
        market="CN",
        timezone="Asia/Shanghai",
        market_close_time=time(15, 0),
        market_open_time=time(9, 30),
        default_universe="cn_csi300_watchlist",
        primary_benchmark="510300.SH",
        broad_benchmark="510500.SH",
        risk_benchmark="159915.SZ",
    ),
}


def get_quant_market_config(market: str) -> QuantMarketConfig:
    normalized = str(market or "").strip().upper()
    try:
        return QUANT_MARKETS[normalized]
    except KeyError as exc:
        raise ValueError(f"Unsupported quant market={market}; expected US or CN") from exc


def default_universe_for_market(market: str) -> str:
    return get_quant_market_config(market).default_universe


__all__ = ["QUANT_MARKETS", "QuantMarketConfig", "default_universe_for_market", "get_quant_market_config"]

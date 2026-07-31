"""Static provider ordering and operational settings."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from finance_analysis.config.env_parsing import env_bool, env_int, env_str

from .models import Market, market_from_value
from .registry import (
    ADJUSTMENT_FACTORS,
    DAILY_BARS,
    INSTRUMENT_INFO,
    LATEST_MARKET_SNAPSHOT,
    MARKET_INDICES,
    MARKET_STATS,
    MINUTE_BARS,
    REALTIME_QUOTES,
    SECTOR_RANKINGS,
)

FIVE_YEAR_HISTORY_DAYS = 5 * 365
CN_LATEST_DAILY_SEQUENCE = ("tickflow", "akshare", "pytdx", "efinance_snapshot", "baostock", "yfinance")

DEFAULT_PROVIDER_ORDER: dict[tuple[Market, str], tuple[str, ...]] = {
    (Market.CN, DAILY_BARS): ("tickflow", "akshare", "pytdx", "baostock", "yfinance"),
    (Market.US, DAILY_BARS): ("longbridge", "yfinance", "tickflow", "akshare"),
    (Market.HK, DAILY_BARS): ("longbridge", "akshare", "yfinance"),
    (Market.CN, MINUTE_BARS): ("streaming", "longbridge", "efinance", "pytdx", "akshare"),
    (Market.US, MINUTE_BARS): ("streaming", "longbridge", "yfinance"),
    (Market.HK, MINUTE_BARS): ("streaming", "longbridge", "efinance", "akshare"),
    (Market.CN, REALTIME_QUOTES): ("streaming", "longbridge", "pytdx", "efinance", "akshare"),
    (Market.US, REALTIME_QUOTES): ("streaming", "longbridge", "yfinance"),
    (Market.HK, REALTIME_QUOTES): ("streaming", "longbridge", "efinance", "akshare", "yfinance"),
    (Market.CN, LATEST_MARKET_SNAPSHOT): ("efinance", "akshare", "pytdx"),
    (Market.CN, MARKET_INDICES): ("efinance", "akshare", "pytdx"),
    (Market.US, MARKET_INDICES): ("longbridge", "yfinance"),
    (Market.HK, MARKET_INDICES): ("longbridge", "yfinance", "akshare"),
    (Market.CN, MARKET_STATS): ("efinance", "akshare"),
    (Market.CN, SECTOR_RANKINGS): ("efinance", "akshare"),
    (Market.CN, INSTRUMENT_INFO): ("database", "tickflow", "longbridge", "pytdx", "akshare", "yfinance"),
    (Market.US, INSTRUMENT_INFO): ("database", "tickflow", "longbridge", "yfinance", "akshare"),
    (Market.HK, INSTRUMENT_INFO): ("database", "tickflow", "longbridge", "akshare", "yfinance"),
    (Market.CN, ADJUSTMENT_FACTORS): ("akshare",),
    (Market.US, ADJUSTMENT_FACTORS): ("yfinance",),
    (Market.HK, ADJUSTMENT_FACTORS): ("akshare", "yfinance"),
}


def provider_order(market: Market | str, capability: str) -> tuple[str, ...]:
    key = (market_from_value(market), str(capability).strip().lower())
    try:
        return DEFAULT_PROVIDER_ORDER[key]
    except KeyError as exc:
        raise ValueError(f"No provider order configured for market={key[0].value}, capability={key[1]}") from exc


@dataclass(frozen=True, slots=True)
class DataProviderConfig:
    longbridge_app_key: str | None = None
    longbridge_app_secret: str | None = None
    longbridge_access_token: str | None = None
    prefetch_realtime_quotes: bool = True
    enable_realtime_quote: bool = True
    enable_realtime_technical_indicators: bool = True
    enable_chip_distribution: bool = True
    enable_eastmoney_patch: bool = False
    enable_fundamental_pipeline: bool = True
    fundamental_stage_timeout_seconds: float = 1.5
    fundamental_fetch_timeout_seconds: float = 0.8
    fundamental_retry_max: int = 1
    fundamental_cache_ttl_seconds: int = 120
    fundamental_cache_max_entries: int = 256
    market_data_initial_daily_days: int = FIVE_YEAR_HISTORY_DAYS
    market_data_refresh_daily_days: int = 60
    market_data_retention_daily_days: int = FIVE_YEAR_HISTORY_DAYS
    market_data_longbridge_max_concurrency: int = 5
    market_data_longbridge_max_retries: int = 3
    market_data_yfinance_max_concurrency: int = 3
    market_data_yfinance_max_retries: int = 2

    @property
    def longbridge_configured(self) -> bool:
        return all((self.longbridge_app_key, self.longbridge_app_secret, self.longbridge_access_token))


@lru_cache(maxsize=1)
def get_data_provider_config() -> DataProviderConfig:
    return DataProviderConfig(
        longbridge_app_key=env_str("LONGBRIDGE_APP_KEY") or None,
        longbridge_app_secret=env_str("LONGBRIDGE_APP_SECRET") or None,
        longbridge_access_token=env_str("LONGBRIDGE_ACCESS_TOKEN") or None,
        enable_eastmoney_patch=env_bool("ENABLE_EASTMONEY_PATCH", False),
        market_data_initial_daily_days=env_int("MARKET_DATA_INITIAL_DAILY_DAYS", FIVE_YEAR_HISTORY_DAYS, minimum=1),
        market_data_refresh_daily_days=env_int("MARKET_DATA_REFRESH_DAILY_DAYS", 60, minimum=1),
        market_data_retention_daily_days=env_int("MARKET_DATA_RETENTION_DAILY_DAYS", FIVE_YEAR_HISTORY_DAYS, minimum=1),
        market_data_longbridge_max_concurrency=env_int(
            "MARKET_DATA_LONGBRIDGE_MAX_CONCURRENCY", 5, minimum=1, maximum=5
        ),
        market_data_longbridge_max_retries=env_int("MARKET_DATA_LONGBRIDGE_MAX_RETRIES", 3, minimum=0),
        market_data_yfinance_max_concurrency=env_int("MARKET_DATA_YFINANCE_MAX_CONCURRENCY", 3, minimum=1),
        market_data_yfinance_max_retries=env_int("MARKET_DATA_YFINANCE_MAX_RETRIES", 2, minimum=0),
    )

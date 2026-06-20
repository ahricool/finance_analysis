# -*- coding: utf-8 -*-
"""Market data provider package."""

from finance_analysis.integrations.market_data.base import BaseFetcher, DataFetcherManager
from finance_analysis.integrations.market_data.providers.akshare import AkshareFetcher, is_hk_stock_code
from finance_analysis.integrations.market_data.providers.baostock import BaostockFetcher
from finance_analysis.integrations.market_data.providers.efinance import EfinanceFetcher
from finance_analysis.integrations.market_data.providers.longbridge.market import LongbridgeFetcher
from finance_analysis.integrations.market_data.providers.longbridge.news import LongbridgeNewsFetcher
from finance_analysis.integrations.market_data.providers.pytdx import PytdxFetcher
from finance_analysis.integrations.market_data.providers.tushare import TushareFetcher
from finance_analysis.integrations.market_data.providers.us_index_mapping import (
    US_INDEX_MAPPING,
    get_us_index_yf_symbol,
    is_us_index_code,
    is_us_stock_code,
)
from finance_analysis.integrations.market_data.providers.yfinance import YfinanceFetcher

__all__ = [
    "BaseFetcher",
    "DataFetcherManager",
    "EfinanceFetcher",
    "AkshareFetcher",
    "TushareFetcher",
    "PytdxFetcher",
    "BaostockFetcher",
    "YfinanceFetcher",
    "LongbridgeFetcher",
    "LongbridgeNewsFetcher",
    "is_us_index_code",
    "is_us_stock_code",
    "is_hk_stock_code",
    "get_us_index_yf_symbol",
    "US_INDEX_MAPPING",
]

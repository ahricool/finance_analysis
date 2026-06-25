# -*- coding: utf-8 -*-
"""Tests for Efinance full-market realtime snapshot fallback."""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd

from finance_analysis.integrations.market_data.providers.efinance import EfinanceFetcher, _realtime_cache


def test_all_realtime_quotes_uses_https_fallback_when_efinance_fails():
    _realtime_cache["data"] = None
    _realtime_cache["timestamp"] = 0
    fetcher = EfinanceFetcher(sleep_min=0, sleep_max=0)
    fallback_df = pd.DataFrame(
        [
            {
                "代码": "600519",
                "名称": "贵州茅台",
                "最新价": 1200.0,
                "涨跌幅": 1.25,
                "涨跌额": 14.8,
                "昨收": 1185.2,
                "今开": 1188.0,
                "最高": 1208.0,
                "最低": 1180.0,
                "成交量": 100000,
                "成交额": 120000000.0,
                "换手率": 0.2,
                "振幅": 2.36,
            }
        ]
    )

    with patch(
        "finance_analysis.integrations.market_data.providers.efinance._ef_call_with_timeout",
        side_effect=ValueError("bad json"),
    ), patch.object(fetcher, "_fetch_eastmoney_realtime_snapshot_df", return_value=fallback_df):
        rows = fetcher.get_all_realtime_quotes()

    assert rows == [
        {
            "code": "600519",
            "name": "贵州茅台",
            "price": 1200.0,
            "pre_close": 1185.2,
            "open": 1188.0,
            "high": 1208.0,
            "low": 1180.0,
            "change_pct": 1.25,
            "change_amount": 14.8,
            "volume": 100000,
            "amount": 120000000.0,
            "turnover_rate": 0.2,
            "amplitude": 2.36,
        }
    ]

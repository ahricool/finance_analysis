"""Regular-session evaluation window. Sina minute provider stays independent of Trade Engine."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from finance_analysis.integrations.market_data.models import MinuteBarsRequest  # pragma: allowlist secret
from finance_analysis.integrations.market_data.providers.sina_minute import SinaMinuteProvider  # pragma: allowlist secret
from finance_analysis.integrations.market_data.service import _StreamingStateProvider  # pragma: allowlist secret
from finance_analysis.trade_engine.bars import in_evaluation_window  # pragma: allowlist secret

SH = ZoneInfo("Asia/Shanghai")
NY = ZoneInfo("America/New_York")


def test_cn_evaluation_window_covers_session_and_skips_lunch():
    assert in_evaluation_window("CN", datetime(2026, 9, 16, 9, 35, tzinfo=SH)) is True
    assert in_evaluation_window("CN", datetime(2026, 9, 16, 12, 10, tzinfo=SH)) is False
    assert in_evaluation_window("CN", datetime(2026, 9, 16, 15, 4, tzinfo=SH)) is True
    assert in_evaluation_window("CN", datetime(2026, 9, 16, 15, 6, tzinfo=SH)) is False


def test_us_evaluation_window_uses_regular_session():
    assert in_evaluation_window("US", datetime(2026, 9, 16, 9, 35, tzinfo=NY)) is True
    assert in_evaluation_window("US", datetime(2026, 9, 16, 16, 4, tzinfo=NY)) is True
    assert in_evaluation_window("US", datetime(2026, 9, 16, 16, 6, tzinfo=NY)) is False


def test_sina_provider_uses_stock_zh_a_minute_period_5_and_does_not_hardcode_1970():
    calls = []

    def fake(symbol):
        calls.append(symbol)
        return pd.DataFrame(
            [
                {"day": "2026-09-16 09:35:00", "open": 10, "high": 11, "low": 9, "close": 10, "volume": 100, "amount": 1000},
                {"day": "2026-09-16 15:00:00", "open": 10, "high": 11, "low": 9, "close": 10.2, "volume": 100, "amount": 1020},
            ]
        )

    provider = SinaMinuteProvider(fetch_frame=fake)
    start = datetime(2026, 9, 16, 1, tzinfo=ZoneInfo("UTC"))
    end = datetime(2026, 9, 16, 8, tzinfo=ZoneInfo("UTC"))
    result = provider.fetch_minute_bars(MinuteBarsRequest(("600519.SH",), start, end, interval="5m"))
    assert calls == ["sh600519"]
    assert len(result.data["600519.SH"]) == 2
    with pytest.raises(ValueError, match="5m"):
        provider.fetch_minute_bars(MinuteBarsRequest(("600519.SH",), start, end, interval="1m"))


def test_streaming_refuses_to_relabel_1m_as_5m():
    provider = _StreamingStateProvider(source=object())
    start = datetime(2026, 9, 16, 1, tzinfo=ZoneInfo("UTC"))
    end = datetime(2026, 9, 16, 8, tzinfo=ZoneInfo("UTC"))
    with pytest.raises(ValueError, match="1m only"):
        provider.fetch_minute_bars(MinuteBarsRequest(("600519.SH",), start, end, interval="5m"))

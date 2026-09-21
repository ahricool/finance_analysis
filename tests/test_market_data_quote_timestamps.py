"""Provider quote timestamps must describe the observation, not the request."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from finance_analysis.integrations.market_data.models import QuoteRequest
from finance_analysis.integrations.market_data.providers.fuyao import FuyaoProvider
from finance_analysis.integrations.market_data.providers.yfinance import YFinanceProvider


@pytest.mark.parametrize('stamp', [None, 1789743600])
def test_yahoo_us_uses_regular_market_payload(monkeypatch, stamp):
    import yfinance

    ticker = SimpleNamespace(info={
        'regularMarketTime': stamp, 'regularMarketPreviousClose': 100,
        'regularMarketPrice': 103, 'regularMarketOpen': 101,
        'regularMarketDayHigh': 105, 'regularMarketDayLow': 99, 'regularMarketVolume': 123,
    })
    monkeypatch.setattr(yfinance, 'Ticker', lambda _: ticker)
    quote = YFinanceProvider().fetch_quotes(QuoteRequest(('AAPL.US',))).data['AAPL.US']
    assert quote.quote_time == (datetime.fromtimestamp(stamp, timezone.utc) if stamp else None)
    assert (quote.open_price, quote.high, quote.low, quote.price, quote.volume) == (101, 105, 99, 103, 123)


def test_yahoo_hk_keeps_fast_info(monkeypatch):
    import yfinance

    ticker = SimpleNamespace(fast_info={'last_price': 103, 'previous_close': 100})
    monkeypatch.setattr(yfinance, 'Ticker', lambda _: ticker)
    quote = YFinanceProvider().fetch_quotes(QuoteRequest(('00700.HK',))).data['700.HK']
    assert quote.price == 103


def test_fuyao_missing_source_time_stays_missing():
    provider = FuyaoProvider(api_key="test")
    quote = provider._quote({'thscode': '600519.SH', 'last_price': 103}, None)
    assert quote.quote_time is None


@pytest.mark.parametrize('code,has_time', [('AAPL.US', False), ('600519.SH', False), ('700.HK', True)])
def test_longbridge_missing_source_time(monkeypatch, code, has_time):
    from unittest.mock import Mock

    from finance_analysis.integrations.market_data.providers.longbridge.market import LongbridgeProvider

    provider = object.__new__(LongbridgeProvider)
    monkeypatch.setattr(provider, 'is_available_for_request', lambda _: True)
    context = Mock()
    context.quote.return_value = [SimpleNamespace(last_done=103, volume=123)]
    monkeypatch.setattr(provider, '_get_ctx', lambda: context)
    monkeypatch.setattr(provider, '_get_static_info', lambda _: None)
    monkeypatch.setattr(provider, '_compute_volume_ratio', lambda *_: None)
    quote = provider.get_realtime_quote(code)
    assert (quote.quote_time is not None) is has_time

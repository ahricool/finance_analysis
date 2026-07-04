from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

from finance_analysis.backtest.service import BacktestService


class FakeSymbols:
    def __init__(self, symbol):
        self.symbol = symbol

    def get_by_code(self, code):
        return self.symbol if code == self.symbol.code else None


class FakeStocks:
    def __init__(self, bars):
        self.bars = bars

    def daily_coverage(self, symbol_id, start_date, end_date):
        requested = [item for item in self.bars if start_date <= item.date <= end_date]
        return {
            "available_date_from": requested[0].date if requested else None,
            "available_date_to": requested[-1].date if requested else None,
            "available_trading_days": len(requested),
            "missing_open_days": sum(item.open <= 0 for item in requested),
        }

    def get_with_warmup(self, code, start_date, end_date, warmup_days):
        return [item for item in self.bars if item.date <= end_date]

    def get_range(self, code, start_date, end_date):
        return [item for item in self.bars if start_date <= item.date <= end_date]


def make_service(market="US", limit_prices=True):
    start = date(2025, 1, 6)
    expected = BacktestService._expected_dates(market, start, date(2025, 2, 7))
    warmup = [start - timedelta(days=index + 1) for index in range(30)]
    all_dates = sorted(warmup + expected)
    bars = [
        SimpleNamespace(
            date=item, open=10, high=11, low=9, close=10, volume=100,
            amount=1000, suspended=False,
            limit_up=11 if limit_prices else None,
            limit_down=9 if limit_prices else None,
        )
        for item in all_dates
    ]
    suffix = "AAPL.US" if market == "US" else "600519.SH"
    symbol = SimpleNamespace(id=1, code=suffix, market=market, enabled=True, sync_daily=True, lot_size=None)
    return BacktestService(backtests=SimpleNamespace(), symbols=FakeSymbols(symbol), stocks=FakeStocks(bars)), start


def test_preflight_ready_for_complete_us_postgresql_data():
    service, start = make_service("US")
    result = service.preflight(
        {
            "engine": "backtrader", "strategy_key": "sma_cross", "market": "US", "code": "AAPL.US",
            "start_date": start, "end_date": date(2025, 2, 7),
            "parameters": {"fast_window": 5, "slow_window": 20},
        }
    )
    assert result.ready
    assert result.coverage_ratio == 1
    assert result.warmup_days == 21
    assert result.warnings


def test_preflight_rejects_unsupported_market_and_missing_cn_limits():
    service, start = make_service("CN", limit_prices=False)
    result = service.preflight(
        {
            "engine": "rqalpha", "strategy_key": "sma_cross", "market": "CN", "code": "600519.SH",
            "start_date": start, "end_date": date(2025, 2, 7),
            "parameters": {"fast_window": 5, "slow_window": 20},
        }
    )
    assert not result.ready
    assert any("涨跌停" in item for item in result.errors)


def test_preflight_rejects_rqalpha_us_without_fallback():
    service, start = make_service("US")
    result = service.preflight(
        {
            "engine": "rqalpha", "strategy_key": "sma_cross", "market": "US", "code": "AAPL.US",
            "start_date": start, "end_date": date(2025, 2, 7), "parameters": {},
        }
    )
    assert not result.ready
    assert any("不支持" in item for item in result.errors)

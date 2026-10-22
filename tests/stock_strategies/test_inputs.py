from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from finance_analysis.market_review.trading_calendar import get_trading_days_between
from finance_analysis.stock_strategies.features import DataNotReady
from finance_analysis.stock_strategies.inputs import InputLoader


class Repository:
    db = None

    def __init__(self):
        self.calls = []
        self.missing_etf = False

    def daily_groups(self, codes, start, end):
        self.calls.append((codes, start, end))
        sessions = get_trading_days_between("us", start, end)
        for code in codes:
            if self.missing_etf and code == "QQQ.US":
                continue
            yield code, [
                dict(date=d, open=100 + i, high=101 + i, low=99 + i, close=100 + i, volume=1e6, amount=1e8)
                for i, d in enumerate(sessions)
            ]

    def market_context(self, market, day):
        return {}, None, None, {}

    def anchor_prices(self, codes, dates):
        self.anchor_request = codes, dates
        return [("A.US", dates[0], 123)]


def universe():
    return dict(
        stocks=["A.US", "B.US"],
        etfs=["QQQ.US"],
        breadth=["A.US"],
        instruments={c: dict(name=c, type="STOCK") for c in ["A.US", "B.US", "QQQ.US"]},
        hash="frozen",
    )


def test_bulk_db_window_bounded_shared_features_and_older_anchor_bridge():
    repo = Repository()
    loader = InputLoader(repository=repo, resolver=SimpleNamespace())
    day, old = date(2026, 10, 19), date(2024, 1, 2)
    data = loader.load("US", day, universe(), anchor_dates=[old.isoformat(), None])
    assert len(repo.calls) == 1
    codes, start, end = repo.calls[0]
    assert set(codes) == {"A.US", "B.US", "QQQ.US", "SPY.US"}
    assert len(get_trading_days_between("us", start, end)) <= 270
    assert data.prices["A.US"][old.isoformat()] == 123
    assert data.provenance["universe_hash"] == "frozen"
    assert data.features["A.US"]["ma200"] > 0
    assert data.next_day == day + timedelta(days=1)


def test_incomplete_etf_window_waits_instead_of_silently_shrinking_pool():
    repo = Repository()
    repo.missing_etf = True
    with pytest.raises(DataNotReady, match="ETF"):
        InputLoader(repository=repo, resolver=SimpleNamespace()).load("US", date(2026, 10, 19), universe())

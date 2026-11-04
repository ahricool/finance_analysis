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


def test_official_stock_trend40_stays_separate_from_independent_etf_trend20(monkeypatch):
    repo = Repository()
    official = {"A.US": dict(trend_score=55, path_score=65), "QQQ.US": dict(trend_score=1)}
    repo.market_context = lambda *_: ({40: dict(regime="RISK_ON", score=80)}, "RISK_ON", None, official)
    monkeypatch.setattr(
        "finance_analysis.stock_strategies.inputs.etf_strength",
        lambda *_: {"A.US": dict(trend_score=99), "QQQ.US": dict(trend_score=70)},
    )
    data = InputLoader(repository=repo, resolver=SimpleNamespace()).load("US", date(2026, 11, 4), universe())
    assert data.trends[40]["A.US"] == official["A.US"]
    assert data.trends[20]["QQQ.US"] == dict(trend_score=70)
    assert "QQQ.US" not in data.trends[40]
    assert "A.US" not in data.trends[20]
    assert "B.US" not in data.trends[40]  # Missing official stocks cannot inherit local ETF scores.
    assert 60 not in data.trends


def test_local_etf_trend20_ignores_prices_before_its_twenty_day_window():
    from copy import deepcopy
    from finance_analysis.stock_strategies.features import indicators, etf_strength

    sessions = get_trading_days_between("us", date(2026, 1, 1), date(2026, 11, 4))[-80:]
    rows = [dict(date=day, open=100 + i, high=101 + i, low=99 + i, close=100 + i,
                 volume=1e6, amount=1e8) for i, day in enumerate(sessions)]
    changed = deepcopy(rows)
    changed[-30].update(open=1000, high=1001, low=999, close=1000)
    original, outside_window = indicators(rows, sessions), indicators(changed, sessions)
    assert original["return20"] == pytest.approx(rows[-1]["close"] / rows[-21]["close"] - 1)
    assert original["slope20"] == outside_window["slope20"]
    assert "slope40" not in original
    baseline = {"SPY.US": original, "A.US": original, "QQQ.US": original}
    alternative = {**baseline, "QQQ.US": outside_window}
    before = etf_strength(baseline, "SPY.US")["QQQ.US"]
    after = etf_strength(alternative, "SPY.US")["QQQ.US"]
    assert after == pytest.approx(before)

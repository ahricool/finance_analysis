"""Consumers select new short-period results without borrowing medium/legacy rows."""

from datetime import date, timedelta
from dataclasses import replace
from types import SimpleNamespace

import pytest

from finance_analysis.database.models.stock import Instrument
from finance_analysis.database.repositories.industry_strength import IndustryStrengthRepository
from finance_analysis.intraday_confirmation.trend import temporary_trend
from finance_analysis.trend_following.config import DEFAULT_CONFIG
from finance_analysis.trend_following.models import DailyBar
from tests.test_trend_following_repository import _Database, _snapshot


def test_industry_rank_date_and_population_are_scoped_to_ten_days():
    db = _Database()
    day = date(2026, 11, 4)
    with db.session_scope() as session:
        session.add(Instrument(id=1, market="CN", code="600001.SH", name="one"))
        for identifier, period in enumerate((10, 20, 40, 60), 1):
            row = _snapshot(snapshot_id=identifier, code="600001.SH", instrument_id=1, trade_date=day)
            row.market, row.trend_period, row.rank = "CN", period, period
            session.add(row)
        later = _snapshot(snapshot_id=5, code="600001.SH", instrument_id=1, trade_date=day + timedelta(days=1))
        later.market, later.trend_period, later.rank = "CN", 20, 1
        session.add(later)
    repo = IndustryStrengthRepository(db)
    assert repo.latest_cn_trend_date() == day
    assert repo.latest_cn_trend_rank_context(["600001.SH"]) == ({"600001.SH": 10}, 1)
    db.engine.dispose()


@pytest.mark.parametrize("period", [10, 20])
def test_intraday_overlay_uses_frozen_period_including_legacy_twenty_day_pools(period, monkeypatch):
    from finance_analysis.intraday_confirmation import trend

    config = replace(DEFAULT_CONFIG, trend_period=period)
    day = date(2026, 11, 4)
    history = [DailyBar(day - timedelta(days=period - i + 1), 100 + i, 101 + i, 99 + i, 100 + i, 1000)
               for i in range(period + 1)]
    price = history[-1].close + 1
    quote = SimpleNamespace(pre_close=history[-1].close, price=price, open_price=price,
                            high=price + 1, low=price - 1, volume=2000)
    seen = []
    calculate = trend.calculate_features

    def record(bars, minimum_bars, selected):
        seen.append(selected.trend_period)
        row = calculate(bars, minimum_bars, selected)
        assert row["return_5d"] == pytest.approx(price / history[-selected.recent_window].close - 1)
        return row

    monkeypatch.setattr(trend, "calculate_features", record)
    official = dict(state="TRENDING", trend_score=70, trend_duration_days=5,
                    features=dict(trend_period=config.trend_period, weighted_slope_percentile=80))
    result = temporary_trend(official, history, quote, history, quote, day, history[-1].trade_date)
    assert seen == [period]
    assert result["temporary_trend_state"] is not None
    assert result["trend_score_delta"] is not None


@pytest.mark.parametrize("key,market,old_period,new_period", [
    ("hybrid_score60", "CN", 20, 10),
    ("trend_quality35", "CN", 20, 10),
    ("ma_market_dd30", "US", 20, 10),
    ("regression_dd20", "US", 60, 40),
])
def test_stock_market_gates_do_not_fall_back_to_original_period(key, market, old_period, new_period):
    from finance_analysis.stock_strategies.engine import initial_state
    from finance_analysis.stock_strategies.features import DataNotReady
    from finance_analysis.stock_strategies.registry import definition
    from finance_analysis.stock_strategies.signals import decide
    from tests.stock_strategies.helpers import inputs

    data = inputs(market=market)
    data.regimes.pop(new_period)
    data.regimes[old_period] = dict(regime="RISK_ON", score=100)
    with pytest.raises(DataNotReady, match=f"Trend{new_period}"):
        decide(definition(key, market), initial_state(), data)

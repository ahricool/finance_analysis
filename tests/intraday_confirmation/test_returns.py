from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from finance_analysis.intraday_confirmation.returns import with_returns
from finance_analysis.integrations.market_data.research import following_sessions

DAY = date(2026, 9, 21)
CONFIRMED = datetime(2026, 9, 21, 14, 15, tzinfo=timezone.utc)


def row(**updates):
    return dict(code="ABC.US", state="CONFIRMED", first_confirmed_at=CONFIRMED.isoformat(),
                first_confirmed_price=110, first_confirmation_open=100,
                first_confirmed_quote_time=(CONFIRMED - timedelta(seconds=1)).isoformat(), **updates)


def bars_for(market="US", day=DAY, scale=1):
    plan = following_sessions(market, day, 10)
    bars = [dict(code="ABC.US", date=d, open=100 * scale, high=150 * scale, low=95 * scale,
                 close=(110 + i) * scale, volume=1000, updated_at=CONFIRMED, data_source="test") for i, d in enumerate([day, *[d for d, _ in plan]])]
    return plan, bars


class Store:
    def __init__(self, bars):
        self.bars = bars
        self.calls = []

    def load_evaluation_bars(self, pairs):
        self.calls.append(pairs)
        return [r for r in self.bars if (r["code"], r["date"]) in pairs]


def test_exact_targets_exclude_confirmation_day_and_do_not_use_current_quote():
    plan, bars = bars_for()
    store = Store(bars)
    original = row(metrics={"price": 9999})
    before = deepcopy(original)
    result = with_returns(store, "US", DAY, [original], plan[-1][1])[0]
    assert result["return_3d"] == pytest.approx(113 / 110 - 1)
    assert result["return_5d"] == pytest.approx(115 / 110 - 1)
    assert result["return_10d"] == pytest.approx(120 / 110 - 1)
    assert len(store.calls) == 1 and len(store.calls[0]) == 11
    assert original == before


@pytest.mark.parametrize("scale", [0.25, 0.98, 2.0])
def test_later_split_or_dividend_scale_does_not_change_return_or_frozen_price(scale):
    plan, bars = bars_for(scale=scale)
    result = with_returns(Store(bars), "US", DAY, [row()], plan[-1][1])[0]
    assert result["first_confirmed_price"] == 110
    assert result["return_10d"] == pytest.approx(120 / 110 - 1)


def test_target_bar_is_not_realized_until_exchange_close_even_if_db_has_it():
    plan, bars = bars_for()
    store = Store(bars)
    before = with_returns(store, "US", DAY, [row()], plan[2][1] - timedelta(microseconds=1))[0]
    assert before["return_3d"] is None and not store.calls
    after = with_returns(store, "US", DAY, [row()], plan[2][1])[0]
    assert after["return_3d"] is not None
    assert after["return_5d"] is None and after["return_10d"] is None
    assert ("ABC.US", plan[3][0]) not in store.calls[0]


@pytest.mark.parametrize("missing_index", [0, 1, 3])
def test_missing_base_or_session_is_null_and_never_shifted_to_later_bar(missing_index):
    plan, bars = bars_for()
    del bars[missing_index]
    result = with_returns(Store(bars), "US", DAY, [row()], plan[-1][1])[0]
    assert result["return_3d"] is None and result["return_10d"] is None


def test_later_gap_does_not_erase_already_complete_shorter_horizon():
    plan, bars = bars_for()
    del bars[4]
    result = with_returns(Store(bars), "US", DAY, [row()], plan[-1][1])[0]
    assert result["return_3d"] is not None
    assert result["return_5d"] is None and result["return_10d"] is None


@pytest.mark.parametrize("field,value", [
    ("first_confirmed_price", None), ("first_confirmed_price", 0), ("first_confirmed_price", float("inf")),
    ("first_confirmation_open", None), ("first_confirmation_open", float("nan")),
    ("first_confirmed_at", None), ("first_confirmed_at", "2026-09-22T14:15:00+00:00"),
    ("first_confirmed_at", "2026-09-21T14:15:00"), ("first_confirmed_quote_time", None),
    ("first_confirmed_quote_time", "2026-09-21T15:15:00+00:00"),
])
def test_missing_or_invalid_anchor_never_falls_back(field, value):
    plan, bars = bars_for()
    store = Store(bars)
    source = row()
    source[field] = value
    result = with_returns(store, "US", DAY, [source], plan[-1][1])[0]
    assert result["return_3d"] is None and not store.calls


@pytest.mark.parametrize("field,value", [("open", None), ("high", 1), ("close", 0), ("volume", 0),
                                           ("close", float("nan")), ("volume", None)])
def test_incomplete_or_invalid_daily_bar_is_unavailable(field, value):
    plan, bars = bars_for()
    bars[2][field] = value
    result = with_returns(Store(bars), "US", DAY, [row()], plan[-1][1])[0]
    assert result["return_3d"] is None


def test_failed_after_first_confirmation_still_has_same_forward_returns():
    plan, bars = bars_for()
    source = row()
    source["state"] = "FAILED"
    assert with_returns(Store(bars), "US", DAY, [source], plan[-1][1])[0]["return_3d"] is not None


def test_missing_calendar_does_not_use_weekdays(monkeypatch):
    from finance_analysis.market_review import trading_calendar
    monkeypatch.setattr(trading_calendar, "_XCALS_AVAILABLE", False)
    result = with_returns(SimpleNamespace(), "US", DAY, [row()], CONFIRMED + timedelta(days=30))[0]
    assert result["return_3d"] is None


def test_us_holiday_and_early_close_and_cn_golden_week_exact_sessions():
    us = following_sessions("US", date(2026, 11, 24), 3)
    assert [d for d, _ in us] == [date(2026, 11, 25), date(2026, 11, 27), date(2026, 11, 30)]
    assert us[1][1] == datetime(2026, 11, 27, 18, tzinfo=timezone.utc)
    cn = following_sessions("CN", date(2026, 9, 30), 3)
    assert [d for d, _ in cn] == [date(2026, 10, 8), date(2026, 10, 9), date(2026, 10, 12)]


@pytest.mark.parametrize("field,value", [("updated_at", None), ("updated_at", CONFIRMED + timedelta(seconds=1)),
                                         ("data_source", "other"), ("data_source", None), ("data_source", "mixed")])
def test_mixed_or_unknown_adjustment_provenance_is_null(field, value):
    plan, bars = bars_for()
    bars[1][field] = value
    result = with_returns(Store(bars), "US", DAY, [row()], plan[-1][1])[0]
    assert result["return_3d"] is None
    assert "return_evidence" not in result


def test_small_dividend_rolling_refresh_boundary_is_not_a_loss():
    plan, bars = bars_for()
    # A later 0.2% adjustment only rewrote the trailing part of an old window.
    for bar in bars[2:]:
        for key in ("open", "high", "low", "close"):
            bar[key] *= 0.998
        bar["updated_at"] = CONFIRMED + timedelta(days=90)
    result = with_returns(Store(bars), "US", DAY, [row()], CONFIRMED + timedelta(days=100))[0]
    assert all(result[f"return_{n}d"] is None for n in (3, 5, 10))


def test_persisted_realized_ratios_survive_later_missing_or_mixed_data():
    plan, bars = bars_for()
    realized = with_returns(Store(bars), "US", DAY, [row()], plan[-1][1])[0]
    assert set(realized["return_evidence"]) == {"3", "5", "10"}
    source = deepcopy(realized)
    # No live DB access is needed after all outcomes are finalized.
    result = with_returns(SimpleNamespace(), "US", DAY, [source], CONFIRMED + timedelta(days=120))[0]
    assert result["return_10d"] == pytest.approx(120 / 110 - 1)
    evidence = result["return_evidence"]["10"]
    assert len(evidence["inputs"]) == 11 and evidence["target_date"] == plan[-1][0]
    assert evidence["adjustment_generation"] == CONFIRMED.isoformat()
    assert source == realized

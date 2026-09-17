from copy import deepcopy
import pytest
from finance_analysis.market_sentiment.calculator import (
    normalized,
    metrics,
    promotions,
    percentile,
    classify,
    calculate,
)
from finance_analysis.market_sentiment.calendar import sessions_through
from datetime import date


def stock(code="000001.SZ", board=1, **kw):
    return normalized(
        {
            "thscode": code,
            "is_st": False,
            "is_new": False,
            "continue_day_cnt": board,
            "continue_day_text": "首板" if board == 1 else f"{board}连板",
            "price_change_ratio_pct": 10.01,
            "limit_up_time": "10:00",
            "seal_money": 60,
            "max_seal_money": 100,
            **kw,
        }
    )


def test_scope_and_units_missing_fields_do_not_remove_limit_ups():
    rows = [
        stock(),
        stock("000002.SZ", is_st=True),
        stock("000003.SZ", is_new=True),
        stock("000004.SZ", limit_up_time=None, seal_money=None, limit_up_reason=None),
    ]
    m = metrics(rows)
    assert m["upstream_total"] == 4 and m["limit_up_count"] == 2
    assert m["excluded_st_count"] == m["excluded_new_count"] == 1
    assert rows[0]["price_change_ratio"] == pytest.approx(0.1001)
    assert m["valid_limit_up_time_count"] == 1 and m["time_coverage"] == 0.5
    assert m["early_limit_up_ratio"] == 1
    assert m["reasons"] == [{"reason": "未提供原因", "count": 2}]
    assert metrics(rows + [stock("000005.SZ", is_st=None)])["limit_up_count"] is None


@pytest.mark.parametrize(
    "cnt,text,expected",
    [
        (1, "首板", 1),
        (0, "首板", None),
        (4, "5天4板", None),
        (3, "3天3板", 3),
        (9, "9连板", 9),
        (4, "3连板", None),
        (2, None, None),
        (True, "首板", None),
    ],
)
def test_continuity_requires_confirmed_agreement(cnt, text, expected):
    assert stock(continue_day_cnt=cnt, continue_day_text=text)["consecutive_boards"] == expected


def test_real_max_not_truncated_and_reason_whitespace_only():
    result = metrics([stock(board=9, limit_up_reason=" A+B "), stock(limit_up_reason="A+B")])
    assert result["highest_board"] == 9 and result["board_distribution"]["7+"] == 1
    assert result["reasons"] == [{"reason": "A+B", "count": 2}]


@pytest.mark.parametrize(
    "current,peak,value",
    [(0, 10, 0), (10, 0, None), (None, 10, None), (10, None, None), (-1, 10, None), (11, 10, None), (10, 10, 1)],
)
def test_seal_valid_denominators(current, peak, value):
    row = stock(seal_money=current, max_seal_money=peak)
    assert row["seal_retention"] == value
    m = metrics([row])
    assert m["valid_seal_retention_count"] == (0 if value is None else 1)
    assert m["seal_retention_median"] == value


def test_time_validity_and_zero_counts():
    m = metrics([stock(limit_up_time="10:01"), stock("000002.SZ", limit_up_time="invalid")])
    assert m["early_limit_up_ratio"] == 0 and m["valid_limit_up_time_count"] == 1
    assert metrics([])["limit_up_count"] == 0
    assert metrics([])["early_limit_up_ratio"] is None


def test_promotion_matches_codes_not_counts():
    before = [stock("000001.SZ", 2), stock("000002.SZ", 2), stock("000003.SZ", 1)]
    now = [stock("000001.SZ", 3), stock("000004.SZ", 3), stock("000003.SZ", 2)]
    p = promotions(before, now, "2026-09-11", "2026-09-14")
    assert p["2_to_3"]["ratio"] == 0.5
    assert p["2_to_3"]["promoted_codes"] == ["000001.SZ"]
    assert p["2_to_3"]["not_promoted_codes"] == ["000002.SZ"]
    assert p["1_to_2"]["ratio"] == 1
    assert p["3_to_4"]["ratio"] is None
    assert promotions(None, now, None, "2026-09-14")["multi"]["ratio"] is None
    assert promotions(before, [stock("000001.SZ", 3, is_st=True)], "a", "b")["multi"]["ratio"] == 0


def observation(heat=65, l=20, m=10, early=0.7, retention=0.7, promo=0.7, coverage=1, denominator=5):
    return dict(
        heat_score=heat,
        limit_up_count=l,
        multi_board_count=m,
        early_limit_up_ratio=early,
        seal_retention_median=retention,
        time_coverage=coverage,
        seal_retention_coverage=coverage,
        promotions={"multi": {"complete": True, "denominator": denominator, "ratio": promo}},
    )


@pytest.mark.parametrize(
    "current,previous,recent,state",
    [
        (observation(None), None, [], "UNKNOWN"),
        (observation(20), None, [], "ICE"),
        (observation(40, l=10, m=5), observation(65), [observation(65)], "COOLING"),
        (observation(50, l=21), observation(30), [], "REPAIR"),
        (observation(65, l=20, m=9), observation(65), [], "DIVERGENCE"),
        (observation(65, early=0.6, retention=0.6), observation(65), [], "DIVERGENCE"),
        (observation(90), observation(80), [], "CLIMAX"),
        (observation(65), None, [], "ACTIVE"),
        (observation(50), None, [], "NEUTRAL"),
        (observation(90, early=None, retention=None), observation(80), [], "ACTIVE"),
        (observation(90, coverage=0.79), observation(80), [], "ACTIVE"),
        (observation(65, early=0.5, retention=0.5, coverage=0.79), observation(), [], "ACTIVE"),
        (observation(65, early=0.5, promo=0.5, denominator=4), observation(), [], "ACTIVE"),
    ],
)
def test_state_rules(current, previous, recent, state):
    actual, reasons = classify(current, previous, recent)
    assert actual == state and reasons


def test_midrank_history_and_real_adjacent_days():
    assert percentile(10, [10] * 20) == 50
    days = sessions_through(date(2026, 9, 14), 21)
    assert days[-2] == date(2026, 9, 11)
    sources, computed = {}, {}
    for d in days:
        rows = [stock()]
        result = calculate(d, rows, sources, computed, sessions_through(d, 21))
        sources[d], computed[d] = rows, result
    assert result["heat_score"] == 50
    assert all(computed[d]["state"] == "UNKNOWN" for d in days[:-1])
    missing = deepcopy(computed)
    missing.pop(days[-2])
    r = calculate(days[-1], [stock()], {days[-3]: [stock()]}, missing, days)
    assert r["heat_score"] is None and r["promotions"]["1_to_2"]["ratio"] is None
    # Spring Festival closure: no invented weekday sessions.
    feb = sessions_through(date(2026, 2, 24), 2)
    assert feb[-2] == date(2026, 2, 13)

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


@pytest.mark.parametrize("unknown", [dict(continue_day_text="5天4板", continue_day_cnt=4), dict(is_st=None)])
def test_unrelated_today_record_does_not_invalidate_yesterday_cohort(unknown):
    before = [stock("000001.SZ", 2), stock("000002.SZ", 2)]
    today = [stock("000001.SZ", 3)]
    baseline = promotions(before, today, "2026-09-15", "2026-09-16")["2_to_3"]
    result = promotions(before, today + [stock("000009.SZ", **unknown)], "2026-09-15", "2026-09-16")["2_to_3"]
    assert result == baseline
    assert result == dict(
        source_date="2026-09-15",
        target_date="2026-09-16",
        complete=True,
        numerator=1,
        denominator=2,
        ratio=0.5,
        promoted_codes=["000001.SZ"],
        not_promoted_codes=["000002.SZ"],
    )


def test_promotion_tiers_validate_their_own_members():
    before = [stock("000001.SZ", 1), stock("000002.SZ", 2), stock("000003.SZ", 3)]
    today = [stock("000001.SZ", 2), stock("000002.SZ", 4, continue_day_text="5天4板"), stock("000003.SZ", 4)]
    result = promotions(before, today, "before", "today")
    for tier in ("1_to_2", "3_to_4"):
        assert result[tier]["complete"] and result[tier]["ratio"] == 1
    for tier in ("2_to_3", "multi"):
        assert not result[tier]["complete"]
        assert result[tier]["ratio"] is result[tier]["numerator"] is result[tier]["denominator"] is None
        assert result[tier]["not_promoted_codes"] == result[tier]["promoted_codes"] == []


@pytest.mark.parametrize(
    "unknown,invalid",
    [
        (dict(is_st=None, board=2), {"2_to_3", "multi"}),
        (dict(is_new=None, board=1), {"1_to_2"}),
        (dict(board=4, continue_day_text="5天4板"), {"1_to_2", "2_to_3", "3_to_4", "multi"}),
        (dict(is_st=True, is_new=None, continue_day_text=None), set()),
        (dict(is_new=True, is_st=None, continue_day_text=None), set()),
        (dict(is_st=True, continue_day_text=None), set()),
    ],
)
def test_yesterday_unknown_only_invalidates_possible_cohorts(unknown, invalid):
    before = [stock("000001.SZ", 2), stock("000009.SZ", **unknown)]
    result = promotions(before, [stock("000001.SZ", 3)], "before", "today")
    assert {tier for tier, p in result.items() if not p["complete"]} == invalid
    if "2_to_3" not in invalid:
        assert result["2_to_3"]["denominator"] == 1
        assert result["2_to_3"]["ratio"] == 1


@pytest.mark.parametrize("fields", [dict(is_st=None), dict(continue_day_text=None)])
def test_unknown_today_cohort_member_is_not_a_confirmed_failure(fields):
    result = promotions([stock(board=2)], [stock(board=3, **fields)], "before", "today")["2_to_3"]
    assert not result["complete"] and result["ratio"] is None
    assert result["not_promoted_codes"] == []


@pytest.mark.parametrize("fields", [dict(is_st=True), dict(is_new=True, is_st=None)])
def test_today_explicitly_excluded_member_does_not_need_continuity(fields):
    result = promotions([stock(board=2)], [stock(continue_day_text=None, **fields)], "before", "today")["2_to_3"]
    assert result["complete"] and result["ratio"] == 0
    assert result["not_promoted_codes"] == ["000001.SZ"]


def test_promotion_empty_cohort_empty_today_and_missing_source_are_distinct():
    empty = promotions([], [stock(is_st=None)], "before", "today")["2_to_3"]
    assert empty["complete"] and empty["numerator"] == empty["denominator"] == 0 and empty["ratio"] is None
    absent = promotions(None, [], "before", "today")["2_to_3"]
    assert not absent["complete"] and absent["denominator"] is None
    no_survivors = promotions([stock(board=2)], [], "before", "today")["2_to_3"]
    assert no_survivors["complete"] and no_survivors["ratio"] == 0
    wrong_height = promotions([stock(board=2)], [stock(board=2)], "before", "today")["2_to_3"]
    assert wrong_height["complete"] and wrong_height["ratio"] == 0


@pytest.mark.parametrize(
    "day,previous", [(date(2026, 9, 14), date(2026, 9, 11)), (date(2026, 2, 24), date(2026, 2, 13))]
)
def test_promotion_requires_real_adjacent_session_even_with_unrelated_unknown(day, previous):
    sessions = sessions_through(day, 21)
    assert sessions[-2] == previous
    today = [stock(board=3), stock("000009.SZ", 4, continue_day_text="5天4板")]
    result = calculate(day, today, {previous: [stock(board=2)]}, {}, sessions)
    assert result["promotions"]["2_to_3"]["ratio"] == 1
    assert result["boards_complete"] is False and result["heat_score"] is None
    missing = calculate(day, today, {sessions[-3]: [stock(board=2)]}, {}, sessions)
    assert not missing["promotions"]["2_to_3"]["complete"]

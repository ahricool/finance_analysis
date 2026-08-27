from __future__ import annotations

from datetime import date, timedelta

import pytest

from finance_analysis.etf_rotation.backtest.data import expand_env_placeholders, resolve_database_url
from finance_analysis.etf_rotation.backtest.rankings import compute_entry_rankings
from finance_analysis.etf_rotation.backtest.runner import annualized_return, run_rotation_backtest, subtract_months
from finance_analysis.etf_rotation.backtest.simulator import simulate_rotation
from finance_analysis.etf_rotation.backtest.types import OhlcvBar
from finance_analysis.etf_rotation.backtest.universe import a_share_etfs
from finance_analysis.etf_rotation.universe import ETFUniverseMember


def _member(code: str, name: str = "ETF") -> ETFUniverseMember:
    return ETFUniverseMember(code, name, "TECHNOLOGY", "AI", "TECH_SOFTWARE")


def _bar(day: date, open_: float, close: float, volume: float = 1000.0) -> OhlcvBar:
    low = min(open_, close)
    high = max(open_, close)
    return OhlcvBar(day, open_, high, low, close, volume, volume * close)


def _ranking(day: date, ordered: list[str]) -> list[dict]:
    return [
        {
            "trade_date": day,
            "code": code,
            "entry_rank": index,
            "entry_score": 100 - index,
            "momentum_score": 90 - index,
            "rank_5d": index,
        }
        for index, code in enumerate(ordered, start=1)
    ]


def test_a_share_universe_excludes_us_and_overseas_index() -> None:
    members = a_share_etfs()
    codes = {member.code for member in members}
    assert "588000.SH" in codes
    assert "159915.SZ" in codes
    assert "SPY.US" not in codes
    assert "QQQ.US" not in codes
    assert "159941.SZ" not in codes
    assert "513650.SH" not in codes
    assert all(code.endswith((".SH", ".SZ")) for code in codes)
    assert all(member.category != "OVERSEAS_INDEX" for member in members)
    assert all(member.market == "CN" for member in members)


def test_docker_database_url_rewrites_compose_hostname(monkeypatch) -> None:
    monkeypatch.setenv("POSTGRES_USER", "alice")
    monkeypatch.setenv("POSTGRES_PASSWORD", "secret")
    monkeypatch.setenv("POSTGRES_DB", "finance_analysis")
    expanded = expand_env_placeholders(
        "postgresql+psycopg2://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}"
    )
    assert expanded == "postgresql+psycopg2://alice:secret@postgres:5432/finance_analysis"
    resolved = resolve_database_url(expanded)
    assert "@127.0.0.1:5432/" in resolved
    assert "postgres" not in resolved.split("@", 1)[-1]


def test_subtract_months_and_calendar_annualization() -> None:
    assert subtract_months(date(2026, 8, 26), 6) == date(2026, 2, 26)
    assert subtract_months(date(2026, 3, 31), 1) == date(2026, 2, 28)
    calendar, trading = annualized_return(1.0, 1.21, date(2026, 2, 2), date(2026, 8, 2), trading_days=120)
    assert calendar == (1.21 ** (365 / 181) - 1)
    assert trading == (1.21 ** (252 / 120) - 1)


def test_simulate_buy_hold_then_rotate_at_next_open() -> None:
    rankings = {
        date(2026, 2, 1): _ranking(date(2026, 2, 1), ["AAA.SH", "BBB.SH", "CCC.SH"]),
        date(2026, 2, 2): _ranking(date(2026, 2, 2), ["BBB.SH", "AAA.SH", "CCC.SH"]),
        date(2026, 2, 3): _ranking(date(2026, 2, 3), ["BBB.SH", "CCC.SH", "AAA.SH"]),
        date(2026, 2, 4): _ranking(date(2026, 2, 4), ["BBB.SH", "CCC.SH", "AAA.SH"]),
    }
    aaa = {
        date(2026, 2, 1): 9.0,
        date(2026, 2, 2): 10.0,
        date(2026, 2, 3): 10.5,
        date(2026, 2, 4): 11.0,
        date(2026, 2, 5): 11.5,
    }
    bbb = {
        date(2026, 2, 1): 19.0,
        date(2026, 2, 2): 19.5,
        date(2026, 2, 3): 19.8,
        date(2026, 2, 4): 20.0,
        date(2026, 2, 5): 22.0,
    }
    ccc = {day: 30.0 for day in aaa}
    bars = {
        "AAA.SH": [_bar(day, price, price) for day, price in aaa.items()],
        "BBB.SH": [_bar(day, price, price) for day, price in bbb.items()],
        "CCC.SH": [_bar(day, price, price) for day, price in ccc.items()],
    }

    trades, equity, position = simulate_rotation(rankings, bars, date(2026, 2, 2), date(2026, 2, 5))
    assert [(item.side, item.code, item.price) for item in trades] == [
        ("buy", "AAA.SH", 10.0),
        ("sell", "AAA.SH", 11.0),
        ("buy", "BBB.SH", 20.0),
    ]
    assert position == "BBB.SH"
    assert equity[-1].total_equity == pytest.approx(1.21)


def test_entry_rankings_prefer_stronger_momentum_name() -> None:
    start = date(2025, 1, 1)
    days = 61
    rising = [_bar(start + timedelta(days=index), 100 + index, 100 + index) for index in range(days)]
    flat = [_bar(start + timedelta(days=index), 100, 100) for index in range(days)]
    rankings = compute_entry_rankings(
        {"AAA.SH": rising, "BBB.SH": flat},
        [_member("AAA.SH", "Up"), _member("BBB.SH", "Flat")],
    )
    last = rankings[start + timedelta(days=days - 1)]
    assert last[0]["code"] == "AAA.SH"
    assert last[0]["entry_rank"] == 1
    assert last[1]["code"] == "BBB.SH"


def test_run_backtest_buys_previous_day_leader_at_open() -> None:
    start = date(2025, 1, 1)
    values_a = [100 + index for index in range(63)]
    values_b = [100] * 63
    bars = {
        "AAA.SH": [
            _bar(start + timedelta(days=index), value, value) for index, value in enumerate(values_a)
        ],
        "BBB.SH": [
            _bar(start + timedelta(days=index), value, value) for index, value in enumerate(values_b)
        ],
    }
    window_start = start + timedelta(days=61)
    window_end = start + timedelta(days=62)
    result = run_rotation_backtest(
        bars,
        [_member("AAA.SH", "Up"), _member("BBB.SH", "Flat")],
        window_start,
        window_end,
    )
    assert result.trades[0].side == "buy"
    assert result.trades[0].code == "AAA.SH"
    assert result.trades[0].price == values_a[61]
    assert result.final_position == "AAA.SH"
    assert result.total_return == values_a[62] / values_a[61] - 1
    assert result.universe_size == 2

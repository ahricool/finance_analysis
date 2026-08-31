from datetime import date, timedelta

from finance_analysis.etf_rotation.backtest.diagnostics import rotation_speed_diagnostics  # pragma: allowlist secret
from finance_analysis.etf_rotation.backtest.simulator import simulate_strategy  # pragma: allowlist secret
from finance_analysis.etf_rotation.backtest.types import OhlcvBar, StrategySpec  # pragma: allowlist secret


def _bar(day: date, price: float) -> OhlcvBar:
    return OhlcvBar(day, price, price, price, price, 1_000_000, 10_000_000)


def _row(rank: int, *, candidate: bool, action: str) -> dict:
    return {
        "code": "FAST",
        "rank": rank,
        "entry_rank": rank,
        "momentum_rank": rank,
        "entry_score": 80,
        "composite_score": 80 if rank <= 6 else 55,
        "state": "TRENDING",
        "is_candidate": candidate,
        "action": action,
        "absolute_trend_eligible": True,
        "liquidity_eligible": True,
        "relative_strength_ready": True,
        "acceleration_score": 70,
        "ret_3d": 0.01,
        "ret_5d": 0.01,
        "rank_change_1d": 0,
        "stop_loss_pct": 0.05,
    }


def test_fast_backtest_executes_close_signals_at_next_open() -> None:
    first = date(2026, 1, 5)
    second = first + timedelta(days=1)
    third = second + timedelta(days=1)
    rankings = {
        first: [_row(1, candidate=True, action="BUY")],
        second: [_row(7, candidate=False, action="EXIT")],
    }
    spec = StrategySpec("fast", "Fast", max_positions=1, buy_entry_rank=4, fast_rotation=True)
    fills, _equity, _closed = simulate_strategy(
        spec,
        rankings,
        {"FAST": [_bar(first, 100), _bar(second, 101), _bar(third, 102)]},
        first,
        third,
    )
    assert [(fill.side, fill.trade_date, fill.signal_date) for fill in fills] == [
        ("buy", second, first),
        ("sell", third, second),
    ]


def test_rotation_speed_diagnostics_report_capture_and_stale_delay() -> None:
    first = date(2026, 1, 5)
    second = first + timedelta(days=1)
    third = second + timedelta(days=1)
    rankings = {
        first: [_row(1, candidate=False, action="WATCH")],
        second: [_row(2, candidate=True, action="BUY")],
        third: [_row(7, candidate=False, action="EXIT")],
    }
    spec = StrategySpec("fast", "Fast", max_positions=1, buy_entry_rank=4, fast_rotation=True)
    fills, _equity, _closed = simulate_strategy(
        spec,
        rankings,
        {"FAST": [_bar(first, 100), _bar(second, 101), _bar(third, 102), _bar(third + timedelta(days=1), 103)]},
        first,
        third + timedelta(days=1),
    )
    result = rotation_speed_diagnostics(rankings, fills)
    assert result["leader_capture_delay"] == 1
    assert result["stale_hold_days"] == 1

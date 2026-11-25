"""Offline proofs of the independent perpetual-drive signal and exit rules."""

from decimal import Decimal

import pytest

from finance_analysis.paper_trade.strategies import perpetual_drive as drive
from finance_analysis.interfaces.api.v1.schemas.paper_trade import StrategyConfig

D = Decimal
ANCHOR = 20_000 * drive.DAY
CONFIG = {
    "symbol": "BTCUSDT", "name": "V8", "strategy_type": drive.TYPE, "direction": "BOTH",
    "notional": "100", "margin": "50", "max_position": "100", "leverage_limit": 2,
    "max_loss": "5", "stop_pct": "2",
}


def bar(stamp, opening, close, extra="0.1"):
    o, c, wick = D(opening), D(close), D(extra)
    return {"timestamp": stamp, "open": str(o), "close": str(c),
            "high": str(max(o, c) + wick), "low": str(min(o, c) - wick),
            "volume": "1", "turnover": str((o + c) / 2)}


def minutes(anchor=ANCHOR, side=1):
    # First 5m span >0.8%, 15m directional move >1.2%, latest candle directional.
    return [bar(anchor + i * drive.MINUTE, 100 + side * D(i) * D("0.16"),
                100 + side * D(i + 1) * D("0.16")) for i in range(126)]


def days(anchor=ANCHOR):
    return [bar(t, "100", "100", "2") for t in range(anchor - 16 * drive.DAY, anchor + drive.DAY, drive.DAY)]


@pytest.mark.parametrize("side,direction", [(1, "LONG"), (-1, "SHORT")])
def test_first_drive_closed_and_no_replay(side, direction):
    rows = minutes(side=side)
    end = ANCHOR + 15 * drive.MINUTE
    now = end + 20_000
    # Forming bar is evidence of refresh only, not valid OHLC input.
    rows[15] = {"timestamp": end}
    decision = drive.evaluate(rows, rows, days(), now, CONFIG)
    assert decision[0:2] == (end, direction)
    assert decision[2]["anchor"] == ANCHOR
    assert decision[2]["exit_profile"]["atr"] == "0.04"
    assert decision[2]["exit_profile"]["initial_stop"] == "0.02"
    # Repair current minute for subsequent decisions, no second entry in this window.
    rows = minutes(side=side)
    history = minutes(ANCHOR - drive.HOUR, side)
    prior = history[:60]
    assert drive.evaluate(prior + rows, prior + rows, days(), now + 5 * drive.MINUTE, CONFIG)[1] is None


def test_missing_and_forming_data_and_benchmark():
    rows = minutes()
    now = ANCHOR + 15 * drive.MINUTE + 20_000
    assert drive.evaluate(rows[:15], rows, days(), now, CONFIG) is None
    assert drive.evaluate(rows[:6] + rows[7:], rows, days(), now, CONFIG) is None
    assert drive.evaluate(rows, rows, days()[2:], now, CONFIG) is None
    assert drive.evaluate(rows, rows, days(), now - 20_000, CONFIG) is None
    assert drive.evaluate(rows, rows, days(), now + 100_000, CONFIG) is None
    # Altcoin must outperform BTC in the same direction, not compare to itself.
    prior = minutes(ANCHOR - drive.HOUR)[:60]
    assert drive.evaluate(prior + rows, prior + rows, days(), now, {**CONFIG, "symbol": "ETHUSDT"})[1] is None
    bearish = minutes(ANCHOR - drive.HOUR, -1)[:60] + minutes(side=-1)
    assert drive.evaluate(prior + rows, bearish, days(), now, CONFIG)[1] is None


def test_hour_overlap_and_utc_rollover():
    previous = ANCHOR - drive.HOUR
    # Before the new range matures, the previous window can still qualify for the first time.
    rows = [bar(previous + i * drive.MINUTE, "100", "100", "0.5") for i in range(61)]
    rows += [bar(previous + i * drive.MINUTE, 100 + D(i - 61) * D("0.4"),
                 100 + D(i - 60) * D("0.4")) for i in range(61, 71)]
    now = ANCHOR + 5 * drive.MINUTE + 20_000
    result = drive.evaluate(rows, rows, days(), now, CONFIG)
    assert result[1] == "LONG"
    assert result[2]["anchor"] == previous
    # ATR must exclude the UTC day that was still forming at the window's anchor.
    assert drive.daily_atr(days(), previous) == D("0.04")


@pytest.mark.parametrize("quantity,first,second,breach", [(D(1), "103", "105", "102"),
                                                          (D(-1), "97", "95", "98")])
def test_monotonic_ratchet(quantity, first, second, breach):
    profile = drive.exit_profile(D("0.04"), "2")
    assert drive.ratchet(profile, 0, "100", first, quantity) == (1, False)
    assert drive.ratchet(profile, 1, "100", second, quantity) == (2, False)
    assert drive.ratchet(profile, 2, "100", breach, quantity) == (2, True)
    assert D(profile["initial_stop"]) == D("0.02")


def test_configuration_independent_and_bounds():
    parsed = StrategyConfig.model_validate(CONFIG)
    assert parsed.drive_efficiency == D("0.48")
    assert parsed.drive_range_pct == D("0.8")
    with pytest.raises(ValueError):
        StrategyConfig.model_validate({**CONFIG, "drive_efficiency": "1.01"})
    with pytest.raises(ValueError):
        StrategyConfig.model_validate({**CONFIG, "stop_pct": "6"})
    with pytest.raises(ValueError):
        StrategyConfig.model_validate({**CONFIG, "strategy_type": "ema_cross", "fast": 30, "slow": 20})

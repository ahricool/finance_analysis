"""Synthetic indicator tests. History days are constructed, not recorded live OHLCV."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from finance_analysis.portfolio_risk.bars import NormalizedBar, regular_5m_slots  # pragma: allowlist secret
from finance_analysis.portfolio_risk.config import RiskPolicy  # pragma: allowlist secret
from finance_analysis.portfolio_risk.indicators import rvol, vwap_until  # pragma: allowlist secret

SH = ZoneInfo("Asia/Shanghai")
POLICY = RiskPolicy()


def _bar(trade_date, end, *, volume=1000, amount=None, amount_quality="missing", close=Decimal("10")):
    start = end - timedelta(minutes=5)
    return NormalizedBar(
        symbol="600519.SH",
        market="CN",
        trade_date=trade_date,
        bar_start=start,
        bar_end=end,
        session_id=f"{trade_date.isoformat()}|AM" if end.astimezone(SH).hour < 12 else f"{trade_date.isoformat()}|PM",
        open=close,
        high=close + Decimal("0.2"),
        low=close - Decimal("0.2"),
        close=close,
        volume=volume,
        amount=amount,
        amount_quality=amount_quality,
        volume_quality="ok" if volume > 0 else "zero",
        provider="sina_minute",
        closed=True,
        slot_key=end.astimezone(SH).strftime("%H:%M"),
    )


def test_exact_and_proxy_vwap_are_not_mixed_and_unavailable_pauses():
    day = date(2026, 9, 16)
    slot = regular_5m_slots("CN", day)[2][1]
    exact_bars = [
        _bar(day, slot, volume=100, amount=Decimal("1050"), amount_quality="exact", close=Decimal("10.5")),
    ]
    value, mode = vwap_until(exact_bars, exact_bars[0], mode="exact_or_proxy")
    assert mode == "EXACT"
    assert value == Decimal("10.5")
    proxy_bars = [_bar(day, slot, volume=100, amount=None, close=Decimal("12"))]
    value, mode = vwap_until(proxy_bars, proxy_bars[0], mode="exact_or_proxy")
    assert mode == "PROXY"
    missing, mode = vwap_until(proxy_bars, proxy_bars[0], mode="exact_only")
    assert mode == "UNAVAILABLE"
    assert missing is None
    zero, mode = vwap_until([_bar(day, slot, volume=0, amount=None)], _bar(day, slot, volume=0), mode="exact_or_proxy")
    assert mode == "UNAVAILABLE"
    assert zero is None


def test_rvol_unknown_without_ten_complete_days_and_ignores_partial_first_day():
    day = date(2026, 9, 16)
    slots = regular_5m_slots("CN", day)
    partial = [_bar(day, end, volume=1000) for _start, end, _session in slots[-2:]]
    current = partial[-1]
    assert rvol(partial, current, days=10, market="CN") is None
    history = []
    for offset in range(9):
        trade_date = date(2026, 9, 1 + offset)
        for _start, end, _session in regular_5m_slots("CN", trade_date):
            history.append(_bar(trade_date, end, volume=2000))
    history.extend(partial)
    assert rvol(history, current, days=10, market="CN") is None

# -*- coding: utf-8 -*-
"""Position-local 5m metrics. No index, sector, or market comparison."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Sequence

from .indicators import BarIndicators  # pragma: allowlist secret


def _pct(new: Decimal, old: Decimal) -> Decimal | None:
    if old <= 0:
        return None
    return (new / old - Decimal("1")) * Decimal("100")


def local_bar_metrics(rows: Sequence[BarIndicators]) -> dict[str, Any]:
    if not rows:
        return {}
    last = rows[-1]
    prev = rows[-2] if len(rows) >= 2 else None
    ago3 = rows[-4] if len(rows) >= 4 else None
    session = [row for row in rows if row.bar.session_id == last.bar.session_id]
    session_high = max((row.bar.high for row in session), default=last.bar.high)
    session_low = min((row.bar.low for row in session), default=last.bar.low)
    first = session[0] if session else last
    drawdown = None
    if session_high > 0:
        drawdown = (session_high - last.bar.close) / session_high * Decimal("100")
    near_low = session_low > 0 and (last.bar.close - session_low) / session_low * Decimal("100") <= Decimal("0.8")
    high_open_fade = (
        first.bar.open >= first.bar.close
        and last.vwap is not None
        and last.bar.close < last.vwap
        and drawdown is not None
        and drawdown >= Decimal("1.5")
    )
    return {
        "close": last.bar.close,
        "ema20": last.ema20,
        "vwap": last.vwap,
        "rvol": last.rvol,
        "previous_30m_low": last.previous_30m_low,
        "price_below_vwap": last.vwap is not None and last.bar.close < last.vwap,
        "price_below_ema20": last.ema20 is not None and last.bar.close < last.ema20,
        "change_5m": _pct(last.bar.close, prev.bar.close) if prev is not None else None,
        "change_15m": _pct(last.bar.close, ago3.bar.close) if ago3 is not None else None,
        "drawdown_from_high_pct": drawdown,
        "near_session_low": near_low,
        "broke_30m_low": last.previous_30m_low is not None and last.bar.close < last.previous_30m_low,
        "high_rvol": last.rvol is not None and last.rvol >= Decimal("1.5"),
        "high_open_fade": high_open_fade,
        "bar_end": last.bar.bar_end,
    }

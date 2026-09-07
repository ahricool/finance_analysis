"""LONG/FLAT research signals; no orders, balances or paper trading."""

from dataclasses import replace
from datetime import datetime
from decimal import Decimal

from finance_analysis.crypto.features import aggregate, atr, breakout, contiguous_tail, ema
from finance_analysis.crypto.models import Kline, StrategyState
from finance_analysis.crypto.regime import market_regime
from finance_analysis.crypto.risk import initial_stop, trailing_stop


def evaluate(klines: list[Kline], at: datetime, state: StrategyState) -> tuple[StrategyState, dict] | None:
    quarter = contiguous_tail(aggregate(klines, 15, at))
    if not quarter or quarter[-1].close_time != at:
        return None
    hourly = contiguous_tail(aggregate(klines, 60, at))
    current = quarter[-1]
    snapshot = dict(
        symbol="BTCUSDT",
        evaluated_at=at,
        price=current.close,
        regime="UNKNOWN",
        setup="NONE",
        action="HOLD" if state.position_state == "LONG" else "WAIT",
        ema20_1h=None,
        ema50_1h=None,
        ema20_15m=None,
        breakout_level_15m=None,
        volume_ratio_15m=None,
        atr14_15m=None,
        reason="历史不足或存在缺口，等待连续完整 K 线",
    )
    hourly_ready = len(hourly) >= 50 and hourly[-1].close_time == at.replace(minute=0, second=0, microsecond=0)
    if hourly_ready:
        closes = [bar.close for bar in hourly]
        e20, e50 = ema(closes, 20), ema(closes, 50)
        snapshot.update(ema20_1h=e20, ema50_1h=e50, regime=market_regime(hourly[-1].close, e20, e50))
    e15 = ema([bar.close for bar in quarter], 20) if len(quarter) >= 20 else None
    atr14 = atr(quarter) if len(quarter) >= 15 else None
    snapshot.update(ema20_15m=e15, atr14_15m=atr14)
    if len(quarter) >= 21:
        setup, level, ratio = breakout(quarter)
        snapshot.update(setup=setup, breakout_level_15m=level, volume_ratio_15m=ratio)

    if state.position_state == "FLAT":
        if snapshot["regime"] == "BULL" and snapshot["setup"] == "BREAKOUT" and atr14 is not None:
            stop = initial_stop(current.close, atr14)
            # Entry is at this bar's close: its earlier high was before entry.
            state = StrategyState(
                position_state="LONG",
                entry_price=current.close,
                entry_time=at,
                highest_price_since_entry=current.close,
                initial_stop=stop,
                trailing_stop=trailing_stop(current.close, atr14, None),
                updated_at=at,
            )
            snapshot.update(action="BUY", reason="1h 多头，15m 突破前20根高点且成交量确认")
        elif hourly_ready and len(quarter) >= 21:
            snapshot.update(reason="等待 BULL 与放量突破同时成立")
    else:
        highest = max(state.highest_price_since_entry, current.high)
        stop = trailing_stop(highest, atr14, state.trailing_stop) if atr14 is not None else state.trailing_stop
        state = replace(state, highest_price_since_entry=highest, trailing_stop=stop)
        # Existing risk limits remain active even while indicator warmup is interrupted by a gap.
        effective = max(state.initial_stop or Decimal(0), stop or Decimal(0))
        if (e15 is not None and current.close < e15) or current.close <= effective:
            snapshot.update(action="EXIT", reason="15m 收盘跌破 EMA20 或触及有效止损")
        elif hourly_ready and len(quarter) >= 21:
            snapshot.update(action="HOLD", reason="保持 LONG，止损只向上移动")
    snapshot.update(
        position_state="FLAT" if snapshot["action"] == "EXIT" else state.position_state,
        initial_stop=state.initial_stop,
        trailing_stop=state.trailing_stop,
    )
    if snapshot["action"] == "EXIT":
        state = StrategyState(updated_at=at)
    return replace(state, updated_at=at), snapshot

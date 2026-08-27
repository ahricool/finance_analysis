"""T+1 open ETF rotation: hold entry #1 until it leaves the top two."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from finance_analysis.etf_rotation.backtest.types import EquityPoint, OhlcvBar, RotationTrade

HOLD_TOP_N = 2


def _bar_on(bars: Sequence[OhlcvBar], trade_date: date) -> OhlcvBar | None:
    for item in bars:
        if item.trade_date == trade_date:
            return item
    return None


def _tradeable_open(bar: OhlcvBar | None) -> float | None:
    if bar is None or bar.suspended or bar.open <= 0:
        return None
    return float(bar.open)


def _mark_price(bar: OhlcvBar | None) -> float | None:
    if bar is None or bar.close <= 0:
        return _tradeable_open(bar)
    return float(bar.close)


def _leader(ranking: Sequence[Mapping[str, Any]]) -> tuple[str, int] | None:
    if not ranking:
        return None
    top = min(ranking, key=lambda row: int(row["entry_rank"]))
    return str(top["code"]), int(top["entry_rank"])


def _rank_of(ranking: Sequence[Mapping[str, Any]], code: str) -> int | None:
    for row in ranking:
        if str(row["code"]) == code:
            return int(row["entry_rank"])
    return None


def simulate_rotation(
    rankings: Mapping[date, Sequence[Mapping[str, Any]]],
    bars_by_code: Mapping[str, Sequence[OhlcvBar]],
    start: date,
    end: date,
    *,
    initial_equity: float = 1.0,
    hold_top_n: int = HOLD_TOP_N,
) -> tuple[list[RotationTrade], list[EquityPoint], str | None]:
    """Execute previous-session entry ranks at the next session open.

    Rules:
    - Buy yesterday's entry-rank #1 at today's open when flat.
    - If the holding's yesterday rank is worse than ``hold_top_n``, sell at
      today's open and buy the new #1 at the same open.
    - Remaining inventory is marked at the last close.  No fees or slippage.
    """
    if initial_equity <= 0:
        raise ValueError("initial_equity must be positive")
    all_dates = sorted({bar.trade_date for bars in bars_by_code.values() for bar in bars})
    calendar = [trade_date for trade_date in all_dates if start <= trade_date <= end]
    date_index = {trade_date: index for index, trade_date in enumerate(all_dates)}
    cash = float(initial_equity)
    position: str | None = None
    shares = 0.0
    trades: list[RotationTrade] = []
    equity: list[EquityPoint] = []

    for trade_date in calendar:
        full_index = date_index[trade_date]
        signal_date = all_dates[full_index - 1] if full_index else None
        ranking = rankings.get(signal_date) if signal_date is not None else None
        if ranking:
            leader = _leader(ranking)
            held_rank = _rank_of(ranking, position) if position else None
            should_rotate = position is None or held_rank is None or held_rank > hold_top_n
            if should_rotate and leader is not None:
                target_code, target_rank = leader
                if position and position != target_code:
                    sell_open = _tradeable_open(_bar_on(bars_by_code.get(position, ()), trade_date))
                    if sell_open is not None:
                        cash = shares * sell_open
                        trades.append(
                            RotationTrade(
                                trade_date=trade_date,
                                side="sell",
                                code=position,
                                price=sell_open,
                                shares=shares,
                                cash_after=cash,
                                signal_date=signal_date,
                                entry_rank=held_rank,
                            )
                        )
                        position = None
                        shares = 0.0
                if position is None and target_code:
                    buy_open = _tradeable_open(_bar_on(bars_by_code.get(target_code, ()), trade_date))
                    if buy_open is not None and cash > 0:
                        shares = cash / buy_open
                        cash = 0.0
                        position = target_code
                        trades.append(
                            RotationTrade(
                                trade_date=trade_date,
                                side="buy",
                                code=target_code,
                                price=buy_open,
                                shares=shares,
                                cash_after=cash,
                                signal_date=signal_date,
                                entry_rank=target_rank,
                            )
                        )

        position_value = 0.0
        if position:
            marked = _mark_price(_bar_on(bars_by_code.get(position, ()), trade_date))
            if marked is not None:
                position_value = shares * marked
        equity.append(
            EquityPoint(
                trade_date=trade_date,
                cash=cash,
                position=position,
                position_value=position_value,
                total_equity=cash + position_value,
            )
        )
    return trades, equity, position


__all__ = ["HOLD_TOP_N", "simulate_rotation"]

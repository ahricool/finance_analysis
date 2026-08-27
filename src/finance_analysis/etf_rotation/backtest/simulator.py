"""T+1-open multi-name rotation simulator.  Signals are always previous close."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from finance_analysis.etf_rotation.backtest.strategies import (
    buy_candidates,
    exit_reason,
    market_is_risk_off,
    ranking_by_code,
    update_hysteresis_streak,
)
from finance_analysis.etf_rotation.backtest.types import (
    ClosedTrade,
    EquityPoint,
    Fill,
    OhlcvBar,
    OpenPosition,
    StrategySpec,
)


def index_bars(bars_by_code: Mapping[str, Sequence[OhlcvBar]]) -> dict[str, dict[date, OhlcvBar]]:
    return {code: {bar.trade_date: bar for bar in bars} for code, bars in bars_by_code.items()}


def _tradeable(bar: OhlcvBar | None) -> bool:
    return bar is not None and not bar.suspended and bar.open > 0


def _mark(bar: OhlcvBar | None, shares: float) -> float:
    if bar is None or bar.close <= 0:
        return 0.0
    return shares * float(bar.close)


def simulate_strategy(
    spec: StrategySpec,
    rankings: Mapping[date, Sequence[Mapping[str, Any]]],
    bars_by_code: Mapping[str, Sequence[OhlcvBar]],
    start: date,
    end: date,
    *,
    initial_equity: float = 1.0,
) -> tuple[list[Fill], list[EquityPoint], list[ClosedTrade]]:
    if initial_equity <= 0:
        raise ValueError("initial_equity must be positive")
    lookup = index_bars(bars_by_code)
    all_dates = sorted({bar.trade_date for bars in bars_by_code.values() for bar in bars})
    calendar = [day for day in all_dates if start <= day <= end]
    date_index = {day: index for index, day in enumerate(all_dates)}
    cash = float(initial_equity)
    holdings: dict[str, OpenPosition] = {}
    fills: list[Fill] = []
    equity_points: list[EquityPoint] = []
    closed: list[ClosedTrade] = []
    previous_equity = initial_equity
    peak = initial_equity

    for day in calendar:
        full_index = date_index[day]
        signal_date = all_dates[full_index - 1] if full_index else None
        signal_rows = list(rankings.get(signal_date, ())) if signal_date is not None else []
        signal_map = ranking_by_code(signal_rows)
        risk_off = spec.risk_off and market_is_risk_off(signal_rows)

        for position in holdings.values():
            update_hysteresis_streak(position, signal_map.get(position.code), spec)

        exits = [
            code
            for code, position in holdings.items()
            if exit_reason(position, signal_map.get(code), spec) is not None
        ]
        traded_notional = 0.0
        for code in exits:
            position = holdings[code]
            bar = lookup.get(code, {}).get(day)
            if not _tradeable(bar):
                continue
            proceeds = position.shares * bar.open
            cash += proceeds
            traded_notional += abs(proceeds)
            reason = exit_reason(position, signal_map.get(code), spec) or "exit"
            pnl_pct = bar.open / position.entry_price - 1.0
            fills.append(
                Fill(
                    trade_date=day,
                    signal_date=signal_date or day,
                    side="sell",
                    code=code,
                    price=bar.open,
                    shares=position.shares,
                    notional=proceeds,
                    reason=reason,
                    entry_rank=None if signal_map.get(code) is None else int(signal_map[code]["entry_rank"]),
                    momentum_rank=None if signal_map.get(code) is None else int(signal_map[code]["momentum_rank"]),
                    pnl_pct=pnl_pct,
                    holding_days=(day - position.entry_date).days,
                    mae=position.mae,
                    mfe=position.mfe,
                )
            )
            closed.append(
                ClosedTrade(
                    code=code,
                    entry_date=position.entry_date,
                    exit_date=day,
                    entry_price=position.entry_price,
                    exit_price=bar.open,
                    return_pct=pnl_pct,
                    holding_days=(day - position.entry_date).days,
                    mae=position.mae,
                    mfe=position.mfe,
                    reason=reason,
                )
            )
            del holdings[code]

        if signal_rows and not risk_off:
            held = set(holdings)
            candidates = [code for code in buy_candidates(signal_rows, spec) if code not in held]
            slots = spec.max_positions - len(holdings)
            to_buy = candidates[: max(0, slots)]
            if to_buy and cash > 0:
                allocation = cash / len(to_buy)
                for code in to_buy:
                    bar = lookup.get(code, {}).get(day)
                    row = signal_map.get(code)
                    if not _tradeable(bar) or row is None or allocation <= 0:
                        continue
                    shares = allocation / bar.open
                    cash -= allocation
                    traded_notional += allocation
                    stop_pct = float(row["stop_loss_pct"]) if spec.stop_loss else None
                    stop_price = bar.open * (1.0 - stop_pct) if stop_pct is not None else None
                    holdings[code] = OpenPosition(
                        code=code,
                        shares=shares,
                        entry_date=day,
                        entry_price=bar.open,
                        signal_date=signal_date or day,
                        entry_rank=int(row["entry_rank"]),
                        stop_pct=stop_pct,
                        stop_price=stop_price,
                        high_water=bar.open,
                    )
                    fills.append(
                        Fill(
                            trade_date=day,
                            signal_date=signal_date or day,
                            side="buy",
                            code=code,
                            price=bar.open,
                            shares=shares,
                            notional=allocation,
                            reason="entry",
                            entry_rank=int(row["entry_rank"]),
                            momentum_rank=int(row["momentum_rank"]),
                        )
                    )

        names: list[str] = []
        marked_equity = cash
        for code, position in holdings.items():
            bar = lookup.get(code, {}).get(day)
            value = _mark(bar, position.shares)
            if value <= 0 and _tradeable(bar):
                value = position.shares * bar.open
            marked_equity += value
            names.append(code)
            if bar is not None:
                _update_excursions_and_stops(position, bar, spec)

        if marked_equity <= 0:
            marked_equity = cash
        turnover = (0.5 * traded_notional / previous_equity) if previous_equity else 0.0
        daily_return = marked_equity / previous_equity - 1.0 if previous_equity else 0.0
        peak = max(peak, marked_equity)
        drawdown = marked_equity / peak - 1.0 if peak else 0.0
        equity_points.append(
            EquityPoint(
                trade_date=day,
                equity=marked_equity,
                cash=cash,
                cash_ratio=cash / marked_equity if marked_equity else 1.0,
                n_positions=len(holdings),
                daily_return=daily_return,
                drawdown=drawdown,
                turnover=turnover,
                positions=";".join(sorted(names)),
            )
        )
        previous_equity = marked_equity

    return fills, equity_points, closed


def _update_excursions_and_stops(position: OpenPosition, bar: OhlcvBar, spec: StrategySpec) -> None:
    if position.entry_price <= 0:
        return
    low_exc = bar.low / position.entry_price - 1.0
    high_exc = bar.high / position.entry_price - 1.0
    position.mae = min(position.mae, low_exc)
    position.mfe = max(position.mfe, high_exc)
    if bar.close > 0:
        position.high_water = max(position.high_water, bar.close)
    if spec.stop_loss and position.stop_pct is not None:
        if spec.trailing_stop and position.high_water > 0:
            trailed = position.high_water * (1.0 - position.stop_pct)
            if position.stop_price is None or trailed > position.stop_price:
                position.stop_price = trailed
        if position.stop_price is not None and bar.low <= position.stop_price:
            position.stop_hit = True


__all__ = ["index_bars", "simulate_strategy"]

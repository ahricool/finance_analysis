"""Backtrader-native SMA cross strategy."""

from __future__ import annotations

from datetime import date
import math

import backtrader as bt

from finance_analysis.backtest.types import BacktestEquityResult, BacktestTradeResult


class SmaCrossBacktraderStrategy(bt.Strategy):
    params = (
        ("fast_window", 5),
        ("slow_window", 20),
        ("request_start", None),
        ("code", ""),
        ("market_rules", None),
        ("commission_rate", 0.0),
        ("stamp_tax_rate", 0.0),
        ("transfer_fee_rate", 0.0),
    )

    def __init__(self):
        self.fast_ma = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.fast_window)
        self.slow_ma = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.slow_window)
        self.pending_signal: tuple[str, date] | None = None
        self.active_order = None
        self.trades_out: list[BacktestTradeResult] = []
        self.equity_out: list[BacktestEquityResult] = []
        self.entry_total = 0.0
        self.entry_quantity = 0.0
        self.acquired_date: date | None = None

    def next_open(self):
        if not self.pending_signal or self.active_order is not None:
            return
        side, signal_date = self.pending_signal
        self.pending_signal = None
        trading_date = self.data.datetime.date(0)
        open_price = float(self.data.open[0])
        limit_up = float(self.data.limit_up[0]) if math.isfinite(float(self.data.limit_up[0])) else None
        limit_down = float(self.data.limit_down[0]) if math.isfinite(float(self.data.limit_down[0])) else None
        suspended = bool(self.data.suspended[0])
        if not self.p.market_rules.can_fill(
            side=side,
            open_price=open_price,
            limit_up=limit_up,
            limit_down=limit_down,
            suspended=suspended,
        ):
            return
        order = None
        if side == "buy" and self.position.size <= 0:
            cash = float(self.broker.getcash())
            quantity = self.p.market_rules.normalize_buy_quantity(cash / open_price, trading_date)
            while quantity > 0:
                fees = self.p.market_rules.calculate_fees(
                    side="buy",
                    gross_amount=quantity * open_price,
                    commission_rate=self.p.commission_rate,
                    stamp_tax_rate=self.p.stamp_tax_rate,
                    transfer_fee_rate=self.p.transfer_fee_rate,
                )
                if quantity * open_price + fees.total <= cash + 1e-9:
                    break
                quantity -= self.p.market_rules.lot_size(trading_date)
            if quantity > 0:
                order = self.buy(size=quantity)
        elif side == "sell" and self.position.size > 0:
            if self.p.market_rules.can_sell(acquired_date=self.acquired_date, trading_date=trading_date):
                order = self.sell(size=self.position.size)
        if order is not None:
            order.addinfo(signal_date=signal_date, side=side)
            self.active_order = order

    def next(self):
        trading_date = self.data.datetime.date(0)
        if trading_date >= self.p.request_start and len(self) > self.p.slow_window:
            previous_fast, previous_slow = float(self.fast_ma[-1]), float(self.slow_ma[-1])
            current_fast, current_slow = float(self.fast_ma[0]), float(self.slow_ma[0])
            if previous_fast <= previous_slow and current_fast > current_slow:
                self.pending_signal = ("buy", trading_date)
            elif previous_fast >= previous_slow and current_fast < current_slow:
                self.pending_signal = ("sell", trading_date)
        if trading_date >= self.p.request_start:
            cash = float(self.broker.getcash())
            position_value = float(self.position.size * self.data.close[0])
            total = cash + position_value
            self.equity_out.append(
                BacktestEquityResult(
                    trading_date=trading_date,
                    cash=cash,
                    position_value=position_value,
                    total_equity=total,
                    position_pct=position_value / total * 100 if total else 0.0,
                )
            )

    def notify_order(self, order):
        if order.status in (order.Submitted, order.Accepted):
            return
        self.active_order = None
        if order.status != order.Completed:
            return
        side = "buy" if order.isbuy() else "sell"
        quantity = abs(float(order.executed.size))
        price = float(order.executed.price)
        gross = quantity * price
        fees = self.p.market_rules.calculate_fees(
            side=side,
            gross_amount=gross,
            commission_rate=self.p.commission_rate,
            stamp_tax_rate=self.p.stamp_tax_rate,
            transfer_fee_rate=self.p.transfer_fee_rate,
        )
        trade_date = self.data.datetime.date(0)
        pnl = return_pct = None
        if side == "buy":
            self.entry_total = gross + fees.total
            self.entry_quantity = quantity
            self.acquired_date = trade_date
        elif self.entry_quantity:
            proceeds = gross - fees.total
            pnl = proceeds - self.entry_total
            return_pct = pnl / self.entry_total * 100 if self.entry_total else 0.0
            self.entry_total = 0.0
            self.entry_quantity = 0.0
            self.acquired_date = None
        self.trades_out.append(
            BacktestTradeResult(
                code=self.p.code,
                engine_order_id=str(order.ref),
                side=side,
                signal_date=order.info.signal_date,
                order_date=trade_date,
                trade_date=trade_date,
                quantity=quantity,
                price=price,
                gross_amount=gross,
                commission=fees.commission,
                tax=fees.tax,
                other_fee=fees.other_fee,
                total_fee=fees.total,
                cash_after=float(self.broker.getcash()),
                position_after=float(self.position.size),
                return_pct=return_pct,
                pnl=pnl,
                exit_reason="death_cross" if side == "sell" else None,
            )
        )


__all__ = ["SmaCrossBacktraderStrategy"]

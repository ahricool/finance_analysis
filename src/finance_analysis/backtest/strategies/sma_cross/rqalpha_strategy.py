"""RQAlpha-native functions for the SMA cross strategy."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from rqalpha.core.events import EVENT
from rqalpha.environment import Environment

from finance_analysis.backtest.market_rules.registry import BaseMarketRules
from finance_analysis.backtest.strategies.sma_cross.common import SmaCrossSignalState
from finance_analysis.backtest.types import BacktestEquityResult, BacktestRequest, BacktestTradeResult


@dataclass
class RQAlphaCollector:
    trades: list[BacktestTradeResult] = field(default_factory=list)
    equity: list[BacktestEquityResult] = field(default_factory=list)
    context: object | None = None
    active_signal_date: date | None = None
    entry_total: float = 0.0


def build_rqalpha_functions(request: BacktestRequest, rules: BaseMarketRules, collector: RQAlphaCollector):
    from rqalpha.api import order_shares, subscribe

    def init(context):
        collector.context = context
        context.signal_state = SmaCrossSignalState(
            request.parameters["fast_window"], request.parameters["slow_window"]
        )
        context.pending_signal = None
        subscribe(request.code)

        def on_trade(event):
            trade = event.trade
            side = trade.side.name.lower()
            quantity = float(trade.last_quantity)
            price = float(trade.last_price)
            gross = quantity * price
            total_fee = float(trade.transaction_cost)
            pnl = return_pct = None
            if side == "buy":
                collector.entry_total = gross + total_fee
            elif collector.entry_total:
                pnl = gross - total_fee - collector.entry_total
                return_pct = pnl / collector.entry_total * 100
                collector.entry_total = 0.0
            portfolio = context.portfolio
            position = portfolio.positions[request.code]
            collector.trades.append(
                BacktestTradeResult(
                    code=request.code,
                    engine_order_id=str(trade.order_id),
                    side=side,
                    signal_date=collector.active_signal_date or trade.trading_datetime.date(),
                    order_date=trade.trading_datetime.date(),
                    trade_date=trade.trading_datetime.date(),
                    quantity=quantity,
                    price=price,
                    gross_amount=gross,
                    commission=float(trade.commission),
                    tax=float(trade.tax),
                    other_fee=max(0.0, total_fee - float(trade.commission) - float(trade.tax)),
                    total_fee=total_fee,
                    cash_after=float(portfolio.cash),
                    position_after=float(position.quantity),
                    return_pct=return_pct,
                    pnl=pnl,
                    exit_reason="death_cross" if side == "sell" else None,
                )
            )

        Environment.get_instance().event_bus.add_listener(EVENT.TRADE, on_trade)

    def before_trading(context):
        del context

    def open_auction(context, bar_dict):
        pending = context.pending_signal
        if not pending:
            return
        side, signal_date = pending
        bar = bar_dict[request.code]
        open_price = float(bar.open)
        if open_price <= 0:
            return
        position = context.portfolio.positions[request.code]
        collector.active_signal_date = signal_date
        if side == "buy" and position.quantity <= 0:
            cash = float(context.portfolio.cash)
            quantity = rules.normalize_buy_quantity(cash / open_price, context.now.date())
            while quantity > 0:
                fees = rules.calculate_fees(
                    side="buy",
                    gross_amount=quantity * open_price,
                    commission_rate=request.commission_rate,
                    stamp_tax_rate=request.stamp_tax_rate,
                    transfer_fee_rate=request.transfer_fee_rate,
                )
                if quantity * open_price + fees.total <= cash + 1e-9:
                    break
                quantity -= rules.lot_size(context.now.date())
            if quantity > 0:
                order_shares(request.code, quantity)
        elif side == "sell" and position.quantity > 0:
            order_shares(request.code, -position.quantity)
        context.pending_signal = None

    def handle_bar(context, bar_dict):
        trading_date = context.now.date()
        signal = context.signal_state.update(float(bar_dict[request.code].close))
        if trading_date >= request.start_date and signal:
            context.pending_signal = (signal, trading_date)

    def after_trading(context):
        trading_date = context.now.date()
        if trading_date < request.start_date:
            return
        portfolio = context.portfolio
        position_value = float(portfolio.positions[request.code].market_value)
        total = float(portfolio.total_value)
        collector.equity.append(
            BacktestEquityResult(
                trading_date=trading_date,
                cash=float(portfolio.cash),
                position_value=position_value,
                total_equity=total,
                position_pct=position_value / total * 100 if total else 0.0,
            )
        )

    return {
        "init": init,
        "before_trading": before_trading,
        "open_auction": open_auction,
        "handle_bar": handle_bar,
        "after_trading": after_trading,
    }


__all__ = ["RQAlphaCollector", "build_rqalpha_functions"]

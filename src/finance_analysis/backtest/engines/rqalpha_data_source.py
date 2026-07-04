"""In-process RQAlpha DataSource backed exclusively by loaded PostgreSQL rows."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Iterable

import numpy as np
import pandas as pd
from rqalpha.const import INSTRUMENT_TYPE, MARKET, TRADING_CALENDAR_TYPE
from rqalpha.interface import (
    AbstractDataSource,
    AbstractMod,
    AbstractTransactionCostDecider,
    ExchangeRate,
    TransactionCost,
)
from rqalpha.model.instrument import Instrument
from rqalpha.utils.datetime_func import convert_date_to_int

from finance_analysis.backtest.types import BacktestRequest, DailyBar

BAR_DTYPE = np.dtype(
    [
        ("datetime", "<i8"),
        ("open", "<f8"),
        ("high", "<f8"),
        ("low", "<f8"),
        ("close", "<f8"),
        ("volume", "<f8"),
        ("total_turnover", "<f8"),
        ("limit_up", "<f8"),
        ("limit_down", "<f8"),
        ("open_interest", "<f8"),
    ]
)


class PostgreSQLRQAlphaDataSource(AbstractDataSource):
    """RQAlpha adapter over an immutable request loaded from PostgreSQL by the service."""

    def __init__(self, request: BacktestRequest):
        if request.market != "CN":
            raise ValueError("RQAlpha PostgreSQL adapter currently supports CN only")
        self.request = request
        self._bars = {request.code: tuple(request.bars)}
        if request.benchmark_code and request.benchmark_bars:
            self._bars[request.benchmark_code] = tuple(request.benchmark_bars)
        self._instruments = {
            code: self._make_instrument(code, request.market, code)
            for code in self._bars
        }
        dates = sorted({bar.trading_date for bars in self._bars.values() for bar in bars})
        self._calendar = pd.DatetimeIndex(dates)

    @staticmethod
    def _make_instrument(code: str, market: str, name: str) -> Instrument:
        exchange = "XSHG" if code.endswith(".SH") else "XSHE"
        return Instrument(
            {
                "order_book_id": code,
                "symbol": name,
                "type": "CS",
                "exchange": exchange,
                "round_lot": 100,
                "board_type": "MainBoard",
                "listed_date": "1990-01-01",
                "de_listed_date": "2999-12-31",
                "market_tplus": 1,
                "status": "Active",
                "special_type": "Normal",
            },
            market=MARKET.CN,
        )

    def get_instruments(self, id_or_syms=None, types=None) -> Iterable[Instrument]:
        values = list(self._instruments.values())
        if id_or_syms is not None:
            wanted = set(id_or_syms)
            values = [item for item in values if item.order_book_id in wanted or item.symbol in wanted]
        if types is not None:
            wanted_types = set(types)
            values = [item for item in values if item.type in wanted_types]
        return values

    def get_trading_calendars(self):
        return {TRADING_CALENDAR_TYPE.CN_STOCK: self._calendar}

    def available_data_range(self, frequency):
        if frequency != "1d":
            raise ValueError("Only daily bars are supported")
        return self._calendar[0].date(), self._calendar[-1].date()

    def _bar_for(self, code: str, dt) -> DailyBar | None:
        target = dt.date() if hasattr(dt, "date") else dt
        return next((bar for bar in self._bars.get(code, ()) if bar.trading_date == target), None)

    @staticmethod
    def _row(bar: DailyBar):
        return (
            convert_date_to_int(bar.trading_date),
            bar.open,
            bar.high,
            bar.low,
            bar.close,
            bar.volume,
            bar.amount or 0.0,
            bar.limit_up if bar.limit_up is not None else np.inf,
            bar.limit_down if bar.limit_down is not None else 0.0,
            0.0,
        )

    def get_bar(self, instrument, dt, frequency):
        if frequency != "1d":
            raise ValueError("Only daily bars are supported")
        bar = self._bar_for(instrument.order_book_id, dt)
        return None if bar is None else np.array(self._row(bar), dtype=BAR_DTYPE)

    def get_open_auction_bar(self, instrument, dt):
        bar = self._bar_for(instrument.order_book_id, dt)
        if bar is None or bar.suspended or bar.open <= 0:
            return None
        return {
            "datetime": convert_date_to_int(bar.trading_date),
            "open": bar.open,
            "last": bar.open,
            "limit_up": bar.limit_up if bar.limit_up is not None else np.inf,
            "limit_down": bar.limit_down if bar.limit_down is not None else 0.0,
            "volume": bar.volume,
            "total_turnover": bar.amount or 0.0,
        }

    def get_open_auction_volume(self, instrument, dt):
        bar = self._bar_for(instrument.order_book_id, dt)
        return 0.0 if bar is None or bar.suspended else bar.volume

    def history_bars(
        self, instrument, bar_count, frequency, fields, dt, skip_suspended=True,
        include_now=False, adjust_type="pre", adjust_orig=None,
    ):
        del adjust_type, adjust_orig
        if frequency != "1d":
            return None
        target = dt.date() if hasattr(dt, "date") else dt
        bars = [bar for bar in self._bars.get(instrument.order_book_id, ()) if bar.trading_date <= target]
        if skip_suspended:
            bars = [bar for bar in bars if not bar.suspended]
        if bar_count is not None:
            bars = bars[-bar_count:]
        data = np.array([self._row(bar) for bar in bars], dtype=BAR_DTYPE)
        if fields is None:
            return data
        if isinstance(fields, str):
            return data[fields]
        return data[fields]

    def get_dividend(self, instrument):
        return None

    def get_split(self, instrument):
        return None

    def get_yield_curve(self, start_date, end_date, tenor=None):
        del tenor
        return pd.DataFrame(index=pd.date_range(start_date, end_date))

    def is_suspended(self, order_book_id, dates):
        return [bool((bar := self._bar_for(order_book_id, dt)) is None or bar.suspended) for dt in dates]

    def is_st_stock(self, order_book_id, dates):
        del order_book_id
        return [False] * len(dates)

    def get_share_transformation(self, order_book_id):
        del order_book_id
        return None

    def get_exchange_rate(self, trading_date, local, settlement=MARKET.CN):
        del trading_date, local, settlement
        return ExchangeRate(1, 1, 1, 1, 1, 1)

    def get_algo_bar(self, id_or_ins, start_min, end_min, dt):
        del id_or_ins, start_min, end_min, dt
        return None

    def get_settle_price(self, instrument, date):
        del instrument, date
        return np.nan

    def history_ticks(self, instrument, count, dt):
        del instrument, count, dt
        return []

    def current_snapshot(self, instrument, frequency, dt):
        raise NotImplementedError

    def get_trading_minutes_for(self, instrument, trading_dt):
        del instrument, trading_dt
        return []

    def get_futures_trading_parameters(self, instrument, dt):
        del instrument, dt
        return None

    def get_merge_ticks(self, order_book_id_list, trading_date, last_dt=None):
        del order_book_id_list, trading_date, last_dt
        return []


_ACTIVE_DATA_SOURCE: ContextVar[PostgreSQLRQAlphaDataSource | None] = ContextVar(
    "rqalpha_postgresql_data_source", default=None
)


class PostgreSQLDataSourceMod(AbstractMod):
    def start_up(self, env, mod_config):
        del mod_config
        source = _ACTIVE_DATA_SOURCE.get()
        if source is None:
            raise RuntimeError("RQAlpha PostgreSQL DataSource was not configured")
        env.set_data_source(source)
        env.set_transaction_cost_decider(INSTRUMENT_TYPE.CS, ProjectStockTransactionCostDecider(source.request))

    def tear_down(self, code, exception=None):
        del code, exception


class ProjectStockTransactionCostDecider(AbstractTransactionCostDecider):
    """Use the same project fee model as Backtrader, including transfer fees."""

    def __init__(self, request: BacktestRequest):
        from finance_analysis.backtest.market_rules import MarketRuleRegistry

        self.request = request
        self.rules = MarketRuleRegistry.get(request.market)

    def calc(self, args):
        side = args.side.name.lower()
        fees = self.rules.calculate_fees(
            side=side,
            gross_amount=float(args.price * args.quantity),
            commission_rate=self.request.commission_rate,
            stamp_tax_rate=self.request.stamp_tax_rate,
            transfer_fee_rate=self.request.transfer_fee_rate,
        )
        return TransactionCost(commission=fees.commission, tax=fees.tax, other_fees=fees.other_fee)


__config__ = {"priority": 200}


def load_mod():
    return PostgreSQLDataSourceMod()


__all__ = ["PostgreSQLRQAlphaDataSource", "_ACTIVE_DATA_SOURCE", "load_mod"]

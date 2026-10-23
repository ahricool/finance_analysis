"""Independent CN quote polling and native minute OHLC snapshot acquisition."""

import asyncio
import logging
from collections import deque
from datetime import timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from finance_analysis.core.time import utc_now
from finance_analysis.integrations.market_data import MarketDataService
from finance_analysis.integrations.market_data.config import CN_STREAM_MINUTE_PROVIDERS
from finance_analysis.integrations.market_data.realtime_state.models import CandleState, MarketEvent
from finance_analysis.market_stream.config import latest_completed_bar_time, market_trading_date
from finance_analysis.market_stream.session import display_day, in_session, session_bounds
from finance_analysis.market_stream.symbol_state import SymbolRuntimeState, SymbolStatus

logger = logging.getLogger(__name__)


class CnQuoteFeed:
    def __init__(self, owner, market_data=None):
        self.owner = owner
        self.market_data = market_data
        self.states = {}
        self.targets = {}
        self.healthy = True
        self.minute_healthy = True
        self._settled = {}
        self._off_session_retry_at = {}
        self._cursor = 0

    async def reconcile(self, targets):
        for symbol in list(self.states):
            if symbol not in targets:
                self.states.pop(symbol)
                self._settled.pop(symbol, None)
                self._off_session_retry_at.pop(symbol, None)
                await self.owner._remove_symbol_state(symbol)
        self.targets = targets
        for symbol in targets:
            if symbol in self.states:
                continue
            cached = await self.owner.repository.get_recent_bars(symbol, self.owner.config.bar_limit)
            current = await self.owner.repository.get_current_candle(symbol)
            if any(
                bar.sampled or bar.source not in CN_STREAM_MINUTE_PROVIDERS
                for bar in [*cached, *([current] if current is not None else [])]
            ):
                await self.owner.repository.clear_intraday(symbol)
                cached = []
            state = SymbolRuntimeState(
                symbol,
                "CN",
                status=SymbolStatus.INSUFFICIENT_HISTORY,
                generation=1,
                quote_subscribed=True,
                candlestick_1m_subscribed=True,
            )
            if cached:
                state.trading_date = cached[-1].bar_time.astimezone(ZoneInfo("Asia/Shanghai")).date()
                self.owner.bars_1m[symbol] = deque(cached, maxlen=self.owner.config.bar_limit)
                state.bars_count = len(cached)
                self.owner.current_candles[symbol] = cached[-1]
            self.states[symbol] = state
            await self.owner._write_symbol_state(state)

    async def run(self):
        while not self.owner.stop_event.is_set():
            started = asyncio.get_running_loop().time()
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.healthy = False
                logger.warning("CN 批量行情采集失败", exc_info=True)
            elapsed = asyncio.get_running_loop().time() - started
            await asyncio.sleep(max(1, 5 - elapsed))

    async def tick(self):
        now = utc_now()
        if not self.targets or not in_session("CN", now):
            return
        market_data = self.market_data
        if market_data is None:
            market_data = self.market_data = MarketDataService()
        requested = set(self.targets)
        result = await asyncio.to_thread(market_data.get_realtime_quotes, sorted(requested), providers=("fuyao",))
        self.healthy = not bool(getattr(result, "failed_symbols", {}))
        now = utc_now()
        for symbol, quote in result.data.items():
            if symbol not in self.targets or symbol not in requested:
                continue
            # A successful HTTP request is not evidence of a fresh market observation.
            at = quote.quote_time
            if at is None or at > now + timedelta(seconds=5) or at.date() != now.date():
                continue
            event = MarketEvent(
                "quote",
                symbol,
                at,
                now,
                None,
                "Intraday",
                {
                    "last_price": quote.price,
                    "open": quote.open_price,
                    "high": quote.high,
                    "low": quote.low,
                    "pre_close": quote.pre_close,
                    "volume": quote.volume,
                    "turnover": quote.amount,
                    "source": "fuyao",
                    "timestamp_kind": "batch",
                },
                self.owner.manager.connection_generation,
            )
            await self.owner._handle_event(event)

    async def run_minutes(self):
        while not self.owner.stop_event.is_set():
            started = asyncio.get_running_loop().time()
            try:
                await self.tick_minutes()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.minute_healthy = False
                logger.warning("CN 原生分钟线采集失败", exc_info=True)
            elapsed = asyncio.get_running_loop().time() - started
            await asyncio.sleep(max(1, self.owner.config.cn_minute_poll_seconds - elapsed))

    async def tick_minutes(self):
        if not self.targets:
            return
        now = utc_now()
        day = display_day("CN", now)
        bounds = session_bounds("CN", day)
        if bounds is None:
            return
        start, close = bounds
        end = min(now, close)
        if end <= start:
            return
        expected = latest_completed_bar_time(end, "CN")
        # At lunch/close, retry until the final closed bar is actually received.
        active = in_session("CN", now)
        symbols = sorted(
            symbol
            for symbol in self.targets
            if active
            or (self._settled.get(symbol) != expected and now >= self._off_session_retry_at.get(symbol, start))
        )
        if not symbols:
            return
        offset = self._cursor % len(symbols)
        symbols = (symbols[offset:] + symbols[:offset])[: self.owner.config.cn_minute_batch_size]
        self._cursor += len(symbols)
        owners = {symbol: self.states[symbol] for symbol in symbols if symbol in self.states}
        if self.market_data is None:
            self.market_data = MarketDataService()
        result = await asyncio.to_thread(
            self.market_data.get_minute_bars,
            symbols,
            start,
            end,
            interval="1m",
            providers=CN_STREAM_MINUTE_PROVIDERS,
            include_incomplete=True,
            minimum_latest_bar_time=expected - timedelta(minutes=2) if expected is not None else None,
        )
        self.minute_healthy = not bool(result.failed_symbols or result.missing_symbols)
        for symbol, state in owners.items():
            if self.states.get(symbol) is not state:
                continue  # Removed/re-added while the HTTP request was running.
            if not active and expected is not None and now - expected > timedelta(minutes=3):
                self._off_session_retry_at[symbol] = now + timedelta(minutes=5)
            values = result.data.get(symbol, [])
            if not values:
                state.error = result.failed_symbols.get(symbol, "minute history unavailable")
                await self.owner._write_symbol_state(state)
                continue
            received_at = utc_now()
            candles = [
                CandleState(
                    symbol=symbol,
                    bar_time=bar.bar_start,
                    open=Decimal(str(bar.open)),
                    high=Decimal(str(bar.high)),
                    low=Decimal(str(bar.low)),
                    close=Decimal(str(bar.close)),
                    volume=bar.volume,
                    turnover=Decimal(str(bar.amount)) if bar.amount is not None else None,
                    trade_session="Intraday",
                    confirmed=bar.bar_end <= end,
                    received_at=received_at,
                    source=bar.provider,
                )
                for bar in values
                if bar.bar_start is not None
                and bar.bar_end is not None
                and market_trading_date(bar.bar_start, "CN") == day
            ]
            if not candles:
                continue
            async with self.owner._symbol_lock(symbol):
                if self.states.get(symbol) is not state or (
                    state.trading_date is not None and day < state.trading_date
                ):
                    continue
                self.owner._cancel_pattern_preview_task(symbol)
                self.owner.pattern_preview_calculated_at.pop(symbol, None)
                # Replace the entire day's source window; never splice competing feeds or sampled bars.
                self.owner.bars_1m[symbol] = deque(candles, maxlen=self.owner.config.bar_limit)
                self.owner.current_candles[symbol] = candles[-1]
                self.owner.pending_candles.pop(symbol, None)  # The complete CN window is published atomically below.
                state.trading_date = day
                state.bars_count = len([bar for bar in candles if bar.confirmed])
                state.status = (
                    SymbolStatus.ACTIVE
                    if state.bars_count >= self.owner.config.minimum_history_bars
                    else SymbolStatus.INSUFFICIENT_HISTORY
                )
                state.last_candle_at = received_at
                state.error = None
                persisted = False
                try:
                    await self.owner.repository.replace_intraday_bars(symbol, candles)
                    self.owner.pending_bars.pop(symbol, None)
                    self.owner.redis_degraded = False
                    persisted = True
                except Exception:
                    self.owner.redis_degraded = True
                    state.error = "minute snapshot cache unavailable"
                    logger.warning("CN 分钟快照写入失败: symbol=%s", symbol, exc_info=True)
                await self.owner._update_trend_state(symbol, "CN", as_of=end)
                await self.owner._update_pattern_state(symbol, "CN")
                await self.owner._write_symbol_state(state)
            if (
                persisted
                and not active
                and expected is not None
                and any(bar.confirmed and bar.bar_time == expected for bar in candles)
            ):
                self._settled[symbol] = expected
        self.minute_healthy = not any(state.error for state in self.states.values())

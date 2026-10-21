"""Independent Fuyao polling; shares the streamer's provider-neutral calculation pipeline."""

import asyncio
import logging
from zoneinfo import ZoneInfo
from collections import deque
from datetime import timedelta

from finance_analysis.core.time import utc_now
from finance_analysis.integrations.market_data import MarketDataService
from finance_analysis.integrations.market_data.realtime_state.models import MarketEvent
from finance_analysis.market_stream.sampling import MinuteSampler
from finance_analysis.market_stream.session import in_session
from finance_analysis.market_stream.symbol_state import SymbolRuntimeState, SymbolStatus

logger = logging.getLogger(__name__)


class CnQuoteFeed:
    def __init__(self, owner, market_data=None):
        self.owner = owner
        self.market_data = market_data
        self.states = {}
        self.targets = {}
        self.sampler = MinuteSampler()
        self.healthy = True

    async def reconcile(self, targets):
        for symbol in list(self.states):
            if symbol not in targets:
                self.sampler.remove(symbol)
                self.states.pop(symbol)
                await self.owner._remove_symbol_state(symbol)
        self.targets = targets
        for symbol in targets:
            if symbol in self.states:
                continue
            cached = await self.owner.repository.get_recent_bars(symbol, self.owner.config.bar_limit)
            if any(not bar.sampled for bar in cached):
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
            await asyncio.sleep(max(1, 10 - elapsed))

    async def tick(self):
        now = utc_now()
        await self._complete(now)
        if not self.targets or not in_session("CN", now):
            return
        market_data = self.market_data
        if market_data is None:
            market_data = self.market_data = MarketDataService()
        requested = set(self.targets)
        result = await asyncio.to_thread(market_data.get_realtime_quotes, sorted(requested), providers=("fuyao",))
        self.healthy = not bool(getattr(result, "failed_symbols", {}))
        now = utc_now()
        await self._complete(now)
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
            candle = self.sampler.observe(quote, now)
            if candle is not None:
                await self.owner._handle_candle(candle, self.owner.manager.connection_generation)

    async def _complete(self, now):
        for candle in self.sampler.advance(now):
            if candle.symbol in self.targets:
                await self.owner._handle_candle(candle, self.owner.manager.connection_generation)

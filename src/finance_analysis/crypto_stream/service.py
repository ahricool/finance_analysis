"""One ingest owner: WS primary, REST fallback, periodic WS recovery."""

import asyncio
import logging
from contextlib import suppress

from finance_analysis.core.time import utc_now
from finance_analysis.database.repositories.crypto import CryptoLeadershipLost

logger = logging.getLogger(__name__)


class CryptoStreamService:
    def __init__(self, service, *, clock=None):
        self.service = service
        self.config = service.config
        self.binance = service.binance
        self.stop = asyncio.Event()
        self.clock = clock

    def request_stop(self):
        self.stop.set()

    async def _work(self):
        bootstrapped = False
        next_http = 0.0
        loop = asyncio.get_running_loop()
        clock = self.clock or loop.time
        while not self.stop.is_set():
            try:
                if not bootstrapped:
                    await self.service.backfill()
                    bootstrapped = True
                async with self.binance.websocket() as socket:
                    first = await self.binance.receive(socket)
                    # Only a valid fresh data frame means recovery, not merely a TCP handshake.
                    self._check_fresh(first)
                    await self.service.reconcile()
                    await self.service.publish(stream_mode="websocket", websocket_connected=True, last_error=None)
                    await self._consume(first)
                    while not self.stop.is_set():
                        row = await self.binance.receive(socket)
                        self._check_fresh(row)
                        await self._consume(row)
            except (asyncio.CancelledError, CryptoLeadershipLost):
                raise
            except Exception as exc:
                logger.warning("BTC WS unavailable; using HTTP fallback: %s", type(exc).__name__)
                await self.service.publish(
                    stream_mode="http_fallback", websocket_connected=False, last_error=type(exc).__name__
                )
            reconnect_at = clock() + self.config.ws_reconnect_interval_seconds
            while not self.stop.is_set():
                if clock() >= next_http:
                    try:
                        await self.service.reconcile()
                    except CryptoLeadershipLost:
                        raise
                    except Exception as exc:
                        logger.warning("BTC HTTP fallback failed: %s", type(exc).__name__)
                        await self.service.publish(last_error=type(exc).__name__)
                    next_http = clock() + self.config.http_fallback_interval_seconds
                if clock() >= reconnect_at:
                    break
                await asyncio.sleep(max(0, min(next_http, reconnect_at) - clock()))

    def _check_fresh(self, row):
        age = (utc_now() - row.close_time).total_seconds()
        if age > 120 or age < -90:
            raise ValueError("Stale Binance kline stream")

    async def _consume(self, row):
        await self.service.ingest([row])
        await self.service.publish(last_websocket_message_time=utc_now())

    async def run(self):
        """Cancel connect/recv/backfill/sleep promptly on SIGTERM, close all transports."""
        worker = asyncio.create_task(self._work())
        stopper = asyncio.create_task(self.stop.wait())
        try:
            await asyncio.wait([worker, stopper], return_when=asyncio.FIRST_COMPLETED)
            if worker.done():
                await worker
        finally:
            worker.cancel()
            stopper.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await worker
            with suppress(asyncio.CancelledError):
                await stopper
            await self.service.publish(websocket_connected=False, ready=False)
            closers = [self.binance.close()]
            if self.service.realtime:
                closers.append(self.service.realtime.close())
            await asyncio.gather(*closers, return_exceptions=True)

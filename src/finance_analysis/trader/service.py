"""Independent elected Trader: stock simulation, Demo execution, Live read-only sync."""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid

from finance_analysis.core.time import utc_now, utc_isoformat
from finance_analysis.integrations.market_data.realtime_state import keys
from finance_analysis.integrations.market_data.realtime_state.repository import RealtimeStateRepository
from finance_analysis.market_stream.config import MarketStreamConfig
from finance_analysis.market_stream.leader_lock import LeaderLock
from finance_analysis.trader.market_cache import ConfirmedBarCache

logger = logging.getLogger(__name__)


class TraderService:
    def __init__(self, *, config=None, repository=None):
        self.config = config or MarketStreamConfig.from_env()
        self.repository = repository or RealtimeStateRepository.from_url(
            self.config.redis_url, bar_limit=self.config.bar_limit, retain_session=True,
        )
        self.redis = self.repository.redis
        self.leader = LeaderLock(
            self.redis, key=keys.TRADER_LEADER_LOCK_KEY, ttl_seconds=self.config.leader_lock_ttl_seconds,
        )
        self.stop_event = asyncio.Event()
        self.instance_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self.statuses = {}
        self.failed = False

    def request_stop(self):
        self.stop_event.set()

    async def _pause(self, seconds):
        try:
            await asyncio.wait_for(self.stop_event.wait(), timeout=seconds)
        except TimeoutError:
            pass

    async def _legacy_streamer_present(self, *, require_heartbeat=True):
        # A pre-split Streamer already owns and may execute Demo strategies.
        # Never start a second executor during a mixed-version upgrade.
        if not await self.redis.get(keys.LEADER_LOCK_KEY):
            return False
        heartbeat = await self.repository.get_heartbeat()
        if not heartbeat:
            return require_heartbeat
        return heartbeat.get("trading_owner") != "trader"

    async def _wait_compatible_streamer(self):
        warned = False
        while not self.stop_event.is_set():
            if not await self._legacy_streamer_present():
                return True
            if not warned:
                logger.warning("Waiting for legacy Streamer trading owner to stop")
                warned = True
            await self._pause(2)
        return False

    async def _renew(self):
        interval = max(1, self.config.leader_lock_ttl_seconds // 3)
        while not self.stop_event.is_set():
            await self._pause(interval)
            if self.stop_event.is_set():
                return
            try:
                if await self.leader.renew():
                    # New Streamer has no trading processes; a legacy owner is
                    # only allowed after this Trader has stopped.
                    if not await self._legacy_streamer_present(require_heartbeat=False):
                        continue
                    logger.error("Legacy Streamer trading owner detected; stopping Trader")
                else:
                    logger.error("Trader leader lease lost")
            except Exception:
                logger.exception("Trader leader check failed")
            self.failed = True
            self.request_stop()
            return

    async def _heartbeat(self):
        while not self.stop_event.is_set():
            try:
                pipe = self.redis.pipeline(transaction=True)
                pipe.hset(keys.TRADER_HEARTBEAT_KEY, mapping={
                    "instance_id": self.instance_id,
                    "status": "READY",
                    "lease_token": self.leader.token,
                    "updated_at": utc_isoformat(utc_now()),
                    **self.statuses,
                })
                pipe.expire(keys.TRADER_HEARTBEAT_KEY, self.config.heartbeat_ttl_seconds)
                await pipe.execute()
            except Exception:
                logger.exception("Trader heartbeat write failed")
            await self._pause(self.config.heartbeat_seconds)

    async def _supervise(self, name, factory):
        while not self.stop_event.is_set():
            self.statuses[name] = "RUNNING"
            try:
                await factory()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.statuses[name] = "RETRYING"
                logger.exception("Trader module %s interrupted", name)
                await self._pause(5)
                continue
            # Paper/Live with missing credentials intentionally return.
            if name == "intraday_options" and not self.stop_event.is_set():
                self.statuses[name] = "RETRYING"
                logger.warning("Trader options scheduler returned unexpectedly")
                await self._pause(5)
                continue
            self.statuses[name] = "INACTIVE"
            return

    async def _run_options(self):
        from finance_analysis.intraday_options.scheduler import run
        await run(self.repository, {}, self.stop_event, bar_source=ConfirmedBarCache(self.repository))

    async def _run_paper(self):
        from finance_analysis.paper_trade.runtime import run_paper_trade
        await run_paper_trade(self.redis, self.leader)

    async def _run_live(self):
        from finance_analysis.live_trade.runtime import run_live_monitor
        await run_live_monitor(self.redis)

    async def run(self):
        from finance_analysis.database.session import DatabaseManager
        acquired = False
        jobs = []
        control = []
        try:
            await asyncio.to_thread(DatabaseManager.get_instance)
            if not await self._wait_compatible_streamer():
                return True
            acquired = await self.leader.acquire()
            if not acquired:
                logger.error("Another Trader already owns the execution lease")
                return False
            logger.info("Trader leader acquired: %s", self.instance_id)
            jobs = [
                asyncio.create_task(self._supervise("intraday_options", self._run_options), name="trader-options"),
                asyncio.create_task(self._supervise("paper_trade", self._run_paper), name="trader-paper"),
                asyncio.create_task(self._supervise("live_monitor", self._run_live), name="trader-live"),
            ]
            control = [
                asyncio.create_task(self._renew(), name="trader-lease"),
                asyncio.create_task(self._heartbeat(), name="trader-heartbeat"),
            ]
            await self.stop_event.wait()
            return not self.failed
        finally:
            self.request_stop()
            # Stop all exchange I/O immediately. The options scheduler already
            # owns a stop_event and drains its bounded computation pool.
            for task in jobs[1:] + control:
                task.cancel()
            await asyncio.gather(*jobs, *control, return_exceptions=True)
            try:
                if acquired:
                    await self.leader.release()
            finally:
                await self.repository.close()
            logger.info("Trader stopped")

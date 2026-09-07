import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace

import pytest

from finance_analysis.core.time import utc_now
from finance_analysis.crypto.config import CryptoConfig
from finance_analysis.crypto_stream.service import CryptoStreamService
from .helpers import candle


@pytest.mark.asyncio
async def test_ws_failure_http_fallback_and_recovery_stops_polling_and_shutdown():
    events = []
    recovered = asyncio.Event()
    receiving = asyncio.Event()
    row = candle(
        open_time=utc_now().replace(second=0, microsecond=0),
        close_time=utc_now().replace(second=0, microsecond=0) + timedelta(minutes=1),
        closed=False,
    )

    class Binance:
        attempts = 0
        count = 0
        closed = False

        @asynccontextmanager
        async def websocket(self):
            self.attempts += 1
            if self.attempts == 1:
                raise OSError("DNS failure")
            try:
                yield self
            finally:
                events.append("socket_closed")

        async def receive(self, _):
            self.count += 1
            if self.count == 1:
                return row
            receiving.set()
            await asyncio.Event().wait()

        async def close(self):
            self.closed = True

    class Service:
        config = CryptoConfig(ws_reconnect_interval_seconds=0.01, http_fallback_interval_seconds=0.005)
        binance = Binance()
        realtime = None
        polls = 0

        async def backfill(self):
            events.append("backfill")

        async def reconcile(self):
            self.polls += 1
            events.append("rest")

        async def publish(self, **data):
            if "stream_mode" in data:
                events.append(data["stream_mode"])
            if data.get("stream_mode") == "websocket":
                recovered.set()

        async def ingest(self, rows):
            assert rows == [row]
            events.append("ingest")

    service = Service()
    stream = CryptoStreamService(service)
    task = asyncio.create_task(stream.run())
    await asyncio.wait_for(recovered.wait(), 1)
    await asyncio.wait_for(receiving.wait(), 1)
    assert events.index("http_fallback") < events.index("rest") < events.index("websocket")
    count = service.polls
    await asyncio.sleep(0.025)
    assert service.polls == count  # More than four poll intervals, but WS now owns ingest.
    stream.request_stop()
    await asyncio.wait_for(task, 1)
    assert service.binance.closed and "socket_closed" in events
    assert events.count("backfill") == 1


@pytest.mark.asyncio
async def test_timeout_and_http_failure_do_not_exit_and_stop_interrupts_retry_sleep():
    fallback = asyncio.Event()
    calls = []

    class Binance:
        @asynccontextmanager
        async def websocket(self):
            yield self

        async def receive(self, _):
            raise TimeoutError("No valid data")

        async def close(self):
            calls.append("closed")

    async def publish(**data):
        if data.get("stream_mode") == "http_fallback":
            fallback.set()

    async def reconcile():
        calls.append("http")
        raise OSError("REST unavailable")

    async def noop():
        pass

    service = SimpleNamespace(
        config=CryptoConfig(), binance=Binance(), realtime=None, publish=publish, reconcile=reconcile, backfill=noop
    )
    stream = CryptoStreamService(service)
    task = asyncio.create_task(stream.run())
    await asyncio.wait_for(fallback.wait(), 1)
    await asyncio.sleep(0)
    assert not task.done()
    stream.request_stop()
    await asyncio.wait_for(task, 1)
    assert calls == ["http", "closed"]


@pytest.mark.asyncio
async def test_shutdown_waits_for_active_db_operation_to_finish():
    import threading
    from finance_analysis.crypto.service import run_db

    entered, release, completed = threading.Event(), threading.Event(), threading.Event()

    def operation():
        entered.set()
        release.wait(timeout=1)
        completed.set()

    task = asyncio.create_task(run_db(operation))
    await asyncio.to_thread(entered.wait, 1)
    task.cancel()
    await asyncio.sleep(0)
    assert not completed.is_set()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert completed.is_set()


@pytest.mark.asyncio
async def test_lost_writer_lock_exits_ingest_and_closes_transport_for_reacquisition():
    from finance_analysis.database.repositories.crypto import CryptoLeadershipLost

    closed = []

    async def backfill():
        raise CryptoLeadershipLost("lost lock")

    async def publish(**data):
        pass

    async def close():
        closed.append(True)

    service = SimpleNamespace(
        config=CryptoConfig(), binance=SimpleNamespace(close=close), realtime=None, backfill=backfill, publish=publish
    )
    with pytest.raises(CryptoLeadershipLost):
        await CryptoStreamService(service).run()
    assert closed == [True]

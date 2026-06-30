from __future__ import annotations

import asyncio
import threading
from datetime import date
from types import SimpleNamespace

import pytest

from finance_analysis.market_stream.subscription_manager import SubscriptionManager
from finance_analysis.market_stream.symbol_state import SubscriptionTarget, SymbolStatus
from finance_analysis.market_stream.watchlist_monitor import WatchListMonitor, load_watchlist_targets
from tests.market_stream.fakes import FakeStreamingClient, wait_until


def target(symbol: str, market_type: str = "US") -> SubscriptionTarget:
    return SubscriptionTarget(symbol=symbol, market_type=market_type)  # type: ignore[arg-type]


def targets(*items: tuple[str, str]) -> dict[str, SubscriptionTarget]:
    return {symbol: target(symbol, market_type) for symbol, market_type in items}


def test_load_watchlist_targets_supports_cn_hk_us_dedup_and_invalid(caplog) -> None:
    repo = SimpleNamespace(
        list_all=lambda: [
            SimpleNamespace(code="600519", market_type="CN"),
            SimpleNamespace(code="000001", market_type="CN"),
            SimpleNamespace(code="HK00700", market_type="HK"),
            SimpleNamespace(code="AAPL", market_type="US"),
            SimpleNamespace(code="AAPL", market_type="US"),
            SimpleNamespace(code="not a symbol", market_type="US"),
        ]
    )
    loaded = load_watchlist_targets(repo)
    assert loaded == targets(
        ("600519.SH", "CN"),
        ("000001.SZ", "CN"),
        ("0700.HK", "HK"),
        ("AAPL.US", "US"),
    )
    assert "跳过" in caplog.text


def test_load_watchlist_targets_includes_holdings_and_deduplicates() -> None:
    watch_repo = SimpleNamespace(list_all=lambda: [SimpleNamespace(code="AAPL", market_type="US")])
    holdings_repo = SimpleNamespace(
        list_all=lambda: [
            SimpleNamespace(code="AAPL", market_type="US"),
            SimpleNamespace(code="HK00700", market_type="HK"),
        ]
    )

    loaded = load_watchlist_targets(watch_repo, holdings_repo)

    assert loaded == targets(("AAPL.US", "US"), ("0700.HK", "HK"))


@pytest.mark.asyncio
async def test_watchlist_snapshot_detects_add_remove_and_market_metadata_change() -> None:
    current = targets(("AAPL.US", "US"), ("0700.HK", "HK"))
    monitor = WatchListMonitor(lambda: current)
    first = await monitor.poll()
    assert first.added == current
    assert first.removed == {}

    unchanged = await monitor.poll()
    assert not unchanged.added and not unchanged.removed

    current = {"AAPL.US": target("AAPL.US", "CN")}
    changed = await monitor.poll()
    assert changed.added["AAPL.US"].market_type == "CN"
    assert changed.removed["AAPL.US"].market_type == "US"
    assert "0700.HK" in changed.removed


def build_manager(*, gate: asyncio.Event | None = None, delay: float = 0):
    clients: list[FakeStreamingClient] = []
    states = []
    warmup_calls: list[tuple[str, str, int]] = []

    def factory():
        client = FakeStreamingClient(operation_delay=delay)
        clients.append(client)
        return client

    async def warmup(symbol, market_type, symbol_generation, connection_generation):
        warmup_calls.append((symbol, market_type, connection_generation))
        if gate is not None:
            await gate.wait()
        return {"symbol": symbol}

    async def apply(state, connection_generation, result, error, finalize):
        finalize(20, error, date(2026, 6, 26))
        return True

    async def state_callback(state):
        states.append((state.symbol, state.market_type, state.status, state.generation))

    async def remove(symbol):
        return None

    manager = SubscriptionManager(
        client_factory=factory,
        event_sink=lambda event: None,
        warmup_loader=warmup,
        warmup_apply=apply,
        state_callback=state_callback,
        removal_callback=remove,
    )
    return manager, clients, states, warmup_calls


@pytest.mark.asyncio
async def test_initial_subscribe_all_markets_preserves_runtime_market_and_is_idempotent() -> None:
    manager, clients, _, warmups = build_manager()
    desired = targets(("600519.SH", "CN"), ("0700.HK", "HK"), ("AAPL.US", "US"))
    manager.desired_targets = desired
    await manager.start()
    await wait_until(lambda: manager.active_symbols == set(desired))
    await manager.reconcile(desired)

    assert [item[0] for item in clients[0].operations].count("subscribe") == 3
    assert {item[:2] for item in warmups} == {
        ("600519.SH", "CN"),
        ("0700.HK", "HK"),
        ("AAPL.US", "US"),
    }
    assert manager.symbol_states["600519.SH"].market_type == "CN"
    assert manager.symbol_states["0700.HK"].market_type == "HK"
    assert manager.symbol_states["AAPL.US"].market_type == "US"
    await manager.stop()


@pytest.mark.asyncio
async def test_deleting_hk_target_only_unsubscribes_hk_symbol() -> None:
    manager, clients, _, _ = build_manager()
    desired = targets(("600519.SH", "CN"), ("0700.HK", "HK"), ("AAPL.US", "US"))
    manager.desired_targets = desired
    await manager.start()
    await wait_until(lambda: manager.active_symbols == set(desired))
    await manager.reconcile(targets(("600519.SH", "CN"), ("AAPL.US", "US")))
    unsubscribe = [item for item in clients[0].operations if item[0] == "unsubscribe"]
    assert unsubscribe == [("unsubscribe", frozenset({"0700.HK"}))]
    await manager.stop()


@pytest.mark.asyncio
async def test_market_metadata_change_removes_then_readds_symbol() -> None:
    manager, clients, _, _ = build_manager()
    manager.desired_targets = targets(("AAPL.US", "US"))
    await manager.start()
    await wait_until(lambda: manager.active_symbols == {"AAPL.US"})
    await manager.reconcile(targets(("AAPL.US", "CN")))
    await wait_until(lambda: manager.symbol_states["AAPL.US"].market_type == "CN")
    operations = [item[0] for item in clients[0].operations]
    assert operations.count("unsubscribe") == 1
    assert operations.count("subscribe") == 2
    await manager.stop()


@pytest.mark.asyncio
async def test_subscribe_unsubscribe_are_serial() -> None:
    manager, clients, _, _ = build_manager(delay=0.01)
    await manager.start()
    await asyncio.gather(
        manager.reconcile(targets(("AAPL.US", "US"))),
        manager.reconcile(targets(("AAPL.US", "US"), ("0700.HK", "HK"))),
        manager.reconcile(targets(("0700.HK", "HK"))),
    )
    await wait_until(lambda: manager.active_symbols == {"0700.HK"})
    assert clients[0].max_concurrent_operations == 1
    await manager.stop()


@pytest.mark.asyncio
async def test_fast_add_delete_cancels_warmup_and_keeps_inactive() -> None:
    gate = asyncio.Event()
    manager, clients, _, _ = build_manager(gate=gate)
    await manager.start()
    await manager.reconcile(targets(("NVDA.US", "US")))
    old_generation = manager.symbol_states["NVDA.US"].generation
    await manager.reconcile({})
    gate.set()
    await asyncio.sleep(0.02)

    state = manager.symbol_states["NVDA.US"]
    assert state.generation > old_generation
    assert state.status == SymbolStatus.INACTIVE
    assert not manager._warmup_tasks
    assert [op[0] for op in clients[0].operations].count("unsubscribe") == 1
    await manager.stop()


@pytest.mark.asyncio
async def test_reconnect_cancels_old_warmups_and_registers_only_new_generation() -> None:
    clients = []
    started: list[tuple[str, int]] = []
    cancelled: list[tuple[str, int]] = []
    gate = asyncio.Event()

    def factory():
        client = FakeStreamingClient()
        clients.append(client)
        return client

    async def warmup(symbol, market_type, symbol_generation, connection_generation):
        started.append((symbol, connection_generation))
        try:
            await gate.wait()
        except asyncio.CancelledError:
            cancelled.append((symbol, connection_generation))
            raise

    async def apply(state, connection_generation, result, error, finalize):
        finalize(0, error, None)
        return True

    async def noop(*args):
        return None

    manager = SubscriptionManager(
        client_factory=factory,
        event_sink=lambda event: None,
        warmup_loader=warmup,
        warmup_apply=apply,
        state_callback=noop,
        removal_callback=noop,
    )
    manager.desired_targets = targets(("AAPL.US", "US"), ("0700.HK", "HK"))
    await manager.start()
    await wait_until(lambda: len(started) == 2)
    old_connection = started[0][1]
    await manager.reconnect()
    await wait_until(lambda: len(started) == 4)
    assert {item for item in cancelled if item[1] == old_connection} == {
        ("AAPL.US", old_connection),
        ("0700.HK", old_connection),
    }
    assert all(key.connection_generation != old_connection for key in manager._warmup_tasks)
    await manager.stop()
    assert not manager._warmup_tasks
    assert len(cancelled) == 4


@pytest.mark.asyncio
async def test_reconnect_resubscribes_and_stale_generation_command_is_dropped() -> None:
    manager, clients, _, _ = build_manager()
    manager.desired_targets = targets(("AAPL.US", "US"))
    await manager.start()
    await wait_until(lambda: manager.active_symbols == {"AAPL.US"})
    old_connection = manager.connection_generation
    changed = await manager._request(
        "reconcile",
        targets(("MSFT.US", "US")),
        connection_generation=old_connection - 1,
    )
    assert changed is False
    assert set(manager.desired_targets) == {"AAPL.US"}

    clients[0].fail_health = True
    await manager.health_check()
    await wait_until(lambda: len(clients) == 2 and manager.active_symbols == {"AAPL.US"})
    assert manager.connection_generation > old_connection
    await manager.stop()


@pytest.mark.asyncio
async def test_history_failure_keeps_subscription_and_can_promote_from_live_bars() -> None:
    clients = []

    def factory():
        client = FakeStreamingClient()
        clients.append(client)
        return client

    async def failed_warmup(symbol, market_type, symbol_generation, connection_generation):
        raise RuntimeError("history unavailable")

    async def apply(state, connection_generation, result, error, finalize):
        finalize(0, error, date(2026, 6, 26))
        return True

    async def noop(*args):
        return None

    manager = SubscriptionManager(
        client_factory=factory,
        event_sink=lambda event: None,
        warmup_loader=failed_warmup,
        warmup_apply=apply,
        state_callback=noop,
        removal_callback=noop,
    )
    await manager.start()
    await manager.reconcile(targets(("AAPL.US", "US")))
    await wait_until(lambda: manager.symbol_states["AAPL.US"].status == SymbolStatus.ERROR)
    await manager.reconcile(targets(("AAPL.US", "US")))
    assert [op[0] for op in clients[0].operations].count("subscribe") == 1
    await manager.bars_updated("AAPL.US", 15, symbol_generation=manager.symbol_states["AAPL.US"].generation)
    assert manager.symbol_states["AAPL.US"].status == SymbolStatus.ACTIVE
    await manager.stop()


@pytest.mark.asyncio
async def test_cancelled_to_thread_result_cannot_modify_new_generation() -> None:
    clients = []
    thread_started = threading.Event()
    thread_release = threading.Event()
    applied_connections: list[int] = []
    first_connection: int | None = None

    def factory():
        client = FakeStreamingClient()
        clients.append(client)
        return client

    def blocking_history():
        thread_started.set()
        thread_release.wait(timeout=2)
        return {"source": "old-thread"}

    async def warmup(symbol, market_type, symbol_generation, connection_generation):
        nonlocal first_connection
        if first_connection is None:
            first_connection = connection_generation
            return await asyncio.to_thread(blocking_history)
        return {"source": "new-connection"}

    async def apply(state, connection_generation, result, error, finalize):
        applied_connections.append(connection_generation)
        finalize(20, error, date(2026, 6, 26))
        return True

    async def noop(*args):
        return None

    manager = SubscriptionManager(
        client_factory=factory,
        event_sink=lambda event: None,
        warmup_loader=warmup,
        warmup_apply=apply,
        state_callback=noop,
        removal_callback=noop,
    )
    manager.desired_targets = targets(("AAPL.US", "US"))
    await manager.start()
    while not thread_started.is_set():
        await asyncio.sleep(0.005)
    assert first_connection is not None
    await manager.reconnect()
    await wait_until(lambda: manager.symbol_states["AAPL.US"].status == SymbolStatus.ACTIVE)
    new_connection = manager.connection_generation
    assert applied_connections == [new_connection]

    thread_release.set()
    await asyncio.sleep(0.05)
    assert applied_connections == [new_connection]
    assert manager.symbol_states["AAPL.US"].status == SymbolStatus.ACTIVE
    await manager.stop()

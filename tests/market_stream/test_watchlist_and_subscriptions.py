from __future__ import annotations

import asyncio

import pytest

from finance_analysis.market_stream.subscription_manager import SubscriptionManager
from finance_analysis.market_stream.symbol_state import SymbolStatus
from finance_analysis.market_stream.watchlist_monitor import WatchListMonitor
from tests.market_stream.fakes import FakeStreamingClient, wait_until


@pytest.mark.asyncio
async def test_watchlist_initial_add_remove_deduplicates_users_and_stable_poll() -> None:
    values = ["AAPL.US", "AAPL.US", "MSFT.US"]
    monitor = WatchListMonitor(lambda: values)  # type: ignore[arg-type]
    desired, added, removed = await monitor.poll()
    assert desired == {"AAPL.US", "MSFT.US"}
    assert added == desired
    assert removed == set()

    values.remove("AAPL.US")
    desired, added, removed = await monitor.poll()
    assert desired == {"AAPL.US", "MSFT.US"}
    assert not added and not removed

    values.remove("AAPL.US")
    desired, added, removed = await monitor.poll()
    assert desired == {"MSFT.US"}
    assert removed == {"AAPL.US"}


def build_manager(*, gate: asyncio.Event | None = None, delay: float = 0):
    clients: list[FakeStreamingClient] = []
    states = []
    warmup_calls: list[str] = []

    def factory():
        client = FakeStreamingClient(operation_delay=delay)
        clients.append(client)
        return client

    async def warmup(symbol, symbol_generation, connection_generation):
        warmup_calls.append(symbol)
        if gate is not None:
            await gate.wait()
        return {"symbol": symbol}

    async def apply(symbol, generation, result, error):
        return 20

    async def state_callback(state):
        states.append((state.symbol, state.status, state.generation))

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
async def test_initial_subscribe_all_and_repeated_reconcile_is_idempotent() -> None:
    manager, clients, _, warmups = build_manager()
    manager.desired_symbols = {"AAPL.US", "MSFT.US"}
    await manager.start()
    await wait_until(lambda: manager.active_symbols == {"AAPL.US", "MSFT.US"})
    await manager.reconcile({"AAPL.US", "MSFT.US"})

    subscribes = [item for item in clients[0].operations if item[0] == "subscribe"]
    assert len(subscribes) == 2
    assert sorted(warmups) == ["AAPL.US", "MSFT.US"]
    await manager.stop()


@pytest.mark.asyncio
async def test_subscribe_unsubscribe_are_serial_and_idempotent() -> None:
    manager, clients, _, _ = build_manager(delay=0.01)
    await manager.start()
    await asyncio.gather(
        manager.reconcile({"AAPL.US"}),
        manager.reconcile({"AAPL.US", "MSFT.US"}),
        manager.reconcile({"MSFT.US"}),
    )
    await wait_until(lambda: manager.active_symbols == {"MSFT.US"})
    await manager.reconcile({"MSFT.US"})
    assert clients[0].max_concurrent_operations == 1
    assert [op[0] for op in clients[0].operations].count("unsubscribe") == 1
    await manager.stop()


@pytest.mark.asyncio
async def test_fast_add_delete_discards_old_warmup_generation() -> None:
    gate = asyncio.Event()
    manager, clients, states, _ = build_manager(gate=gate)
    await manager.start()
    await manager.reconcile({"NVDA.US"})
    old_generation = manager.symbol_states["NVDA.US"].generation
    await manager.reconcile(set())
    gate.set()
    await asyncio.sleep(0.02)

    state = manager.symbol_states["NVDA.US"]
    assert state.generation > old_generation
    assert state.status == SymbolStatus.INACTIVE
    assert "NVDA.US" not in manager.active_symbols
    assert [op[0] for op in clients[0].operations].count("unsubscribe") == 1
    await manager.stop()


@pytest.mark.asyncio
async def test_reconnect_resubscribes_and_stale_generation_command_is_dropped() -> None:
    manager, clients, _, _ = build_manager()
    manager.desired_symbols = {"AAPL.US"}
    await manager.start()
    await wait_until(lambda: manager.active_symbols == {"AAPL.US"})
    old_connection_generation = manager.connection_generation
    changed = await manager._request(
        "reconcile",
        {"MSFT.US"},
        connection_generation=old_connection_generation - 1,
    )
    assert changed is False
    assert manager.desired_symbols == {"AAPL.US"}

    clients[0].fail_health = True
    await manager.health_check()
    await wait_until(lambda: len(clients) == 2 and manager.active_symbols == {"AAPL.US"})
    assert manager.connection_generation > old_connection_generation
    assert any(op[0] == "subscribe" for op in clients[1].operations)
    await manager.stop()


@pytest.mark.asyncio
async def test_subscription_is_established_before_history_loader_starts() -> None:
    manager, clients, _, warmups = build_manager()
    await manager.start()
    await manager.reconcile({"AAPL.US"})
    await wait_until(lambda: bool(warmups))
    assert clients[0].operations[1] == ("subscribe", frozenset({"AAPL.US"}))
    assert warmups == ["AAPL.US"]
    await manager.stop()


@pytest.mark.asyncio
async def test_history_failure_keeps_live_subscription_and_does_not_resubscribe() -> None:
    clients = []

    def factory():
        client = FakeStreamingClient()
        clients.append(client)
        return client

    async def failed_warmup(symbol, symbol_generation, connection_generation):
        raise RuntimeError("history unavailable")

    async def apply(symbol, generation, result, error):
        raise AssertionError("failed history must not be applied")

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
    await manager.reconcile({"AAPL.US"})
    await wait_until(lambda: manager.symbol_states["AAPL.US"].status == SymbolStatus.ERROR)
    await manager.reconcile({"AAPL.US"})
    assert [op[0] for op in clients[0].operations].count("subscribe") == 1
    await manager.bars_updated(
        "AAPL.US", 15, symbol_generation=manager.symbol_states["AAPL.US"].generation
    )
    assert manager.symbol_states["AAPL.US"].status == SymbolStatus.ACTIVE
    await manager.stop()


@pytest.mark.asyncio
async def test_reconnect_reloads_watchlist_before_resubscribing() -> None:
    clients = []
    desired = {"AAPL.US"}

    def factory():
        client = FakeStreamingClient()
        clients.append(client)
        return client

    async def reload_desired():
        return set(desired)

    async def warmup(symbol, symbol_generation, connection_generation):
        return {"symbol": symbol}

    async def apply(symbol, generation, result, error):
        return 20

    async def noop(*args):
        return None

    manager = SubscriptionManager(
        client_factory=factory,
        event_sink=lambda event: None,
        warmup_loader=warmup,
        warmup_apply=apply,
        state_callback=noop,
        removal_callback=noop,
        desired_loader=reload_desired,
    )
    manager.desired_symbols = set(desired)
    await manager.start()
    await wait_until(lambda: manager.active_symbols == {"AAPL.US"})
    desired.clear()
    desired.add("MSFT.US")
    clients[0].fail_health = True
    await manager.health_check()
    await wait_until(lambda: manager.active_symbols == {"MSFT.US"})
    assert manager.symbol_states["AAPL.US"].status == SymbolStatus.INACTIVE
    assert clients[1].operations[1] == ("subscribe", frozenset({"MSFT.US"}))
    await manager.stop()

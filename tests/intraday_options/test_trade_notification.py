"""Offline unit and integration tests for intraday simulation trade notifications."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from finance_analysis.database.models import Notification
from finance_analysis.database.repositories.notification import NotificationRepository
from finance_analysis.integrations.market_data.realtime_state.models import QuoteState
from finance_analysis.integrations.market_data.realtime_state.repository import RealtimeStateRepository
from finance_analysis.intraday_options.notification import (
    is_trade_event,
    notify_trade_events,
    render_trade_notification,
)
from finance_analysis.intraday_options import scheduler
from finance_analysis.notification.config import NotificationConfig
from finance_analysis.notification.noise_control import reset_notification_noise_state
from finance_analysis.notification.service import NotificationResult, NotificationService
from tests.market_stream.fakes import FakeRedis


def _entry_event(*, side: int = 1, target: float | None = 150.28, exit_policy: str | None = "v7_fixed_wave"):
    entry_price = 145.20
    invalidation = round(entry_price * (1 - side * 0.025), 2)
    trade = {
        "id": "NVDA.US:opening_breakout:bullish:2026-11-20T14:30:00+00:00",
        "symbol": "NVDA.US",
        "trading_date": "2026-11-20",
        "process_id": "opening_breakout:bullish:2026-11-20T14:30:00+00:00",
        "side": side,
        "kind": "opening_breakout",
        "entry_price": entry_price,
        "entry_at": "2026-11-20T14:41:05+00:00",
        "entry_price_at": "2026-11-20T14:41:02+00:00",
        "invalidation": invalidation,
        "protection": invalidation,
        "target": target,
        "cutoff": "2026-11-20T20:50:00+00:00",
        "entry_evidence": {
            "target_source": "V7波段止盈(+3.5%)" if target is not None else "移动止损跟踪",
        },
    }
    if exit_policy:
        trade.update(
            exit_policy=exit_policy,
            stop_loss_pct=0.025,
            take_profit_pct=0.035,
            profit_lock_trigger_pct=0.020,
            profit_lock_level_pct=0.002,
        )
    return {
        "kind": "entry",
        "reason": "模拟做多进场" if side == 1 else "模拟做空进场",
        "at": "2026-11-20T14:41:05+00:00",
        "symbol": "NVDA.US",
        "data_time": "2026-11-20T14:41:02+00:00",
        "rule_version": "underlying_sim_v7",
        "trade": trade,
        "trade_id": trade["id"],
    }


def _exit_event(*, side: int = 1, return_pct: float = 3.50, estimated: bool = False):
    entry_price = 145.20
    exit_price = round(entry_price * (1 + side * return_pct / 100.0), 2)
    trade = {
        "id": "NVDA.US:opening_breakout:bullish:2026-11-20T14:30:00+00:00",
        "symbol": "NVDA.US",
        "trading_date": "2026-11-20",
        "process_id": "opening_breakout:bullish:2026-11-20T14:30:00+00:00",
        "side": side,
        "kind": "opening_breakout",
        "entry_price": entry_price,
        "entry_at": "2026-11-20T14:41:05+00:00",
        "exit_price": exit_price,
        "exit_at": "2026-11-20T15:23:20+00:00",
        "exit_price_at": "2026-11-20T15:23:18+00:00",
        "planned_exit_at": "2026-11-20T20:50:00+00:00" if estimated else "2026-11-20T15:23:20+00:00",
        "exit_reason": "当日收盘前清仓" if estimated else "到达波段止盈目标",
        "estimated": estimated,
        "anomaly": "截止行情缺失或重启后补记" if estimated else None,
        "return_pct": return_pct,
        "duration_seconds": 2535.0,
    }
    return {
        "kind": "exit",
        "reason": trade["exit_reason"],
        "at": trade["exit_at"],
        "symbol": "NVDA.US",
        "data_time": trade["exit_price_at"],
        "rule_version": "underlying_sim_v7",
        "trade": trade,
        "trade_id": trade["id"],
    }


def test_render_v7_entry_long_and_short_avoids_telegram_markdown_hazards():
    title, content = render_trade_notification(_entry_event(side=1), symbol_name="英伟达")
    assert title == "日内模拟开仓 · 做多 NVDA.US @ 145.20"
    assert "📈 **日内模拟开仓 · 做多 NVDA.US（英伟达）**" in content
    assert "开盘区间突破" in content
    assert "141.57（-2.50%）" in content
    assert "150.28（+3.50% · V7波段止盈）" in content
    assert "浮盈达 +2.0% 时保护位上移至+0.20%锁盈" in content
    assert "15:50 美东 / 04:50 北京" in content
    assert "09:41:02 美东 / 22:41:02 北京" in content
    # No raw underscores or ASCII brackets that break legacy Telegram Markdown.
    assert "_" not in content
    assert "(" not in content and ")" not in content

    short_title, short_content = render_trade_notification(
        _entry_event(side=-1, target=None, exit_policy=None), symbol_name="NVDA.US"
    )
    assert short_title == "日内模拟开仓 · 做空 NVDA.US @ 145.20"
    assert "📉 **日内模拟开仓 · 做空 NVDA.US**" in short_content
    assert "目标止盈：移动止损跟踪" in short_content
    assert "锁盈规则" not in short_content


def test_render_exit_normal_and_estimated():
    title, content = render_trade_notification(_exit_event(return_pct=3.50, estimated=False), symbol_name="英伟达")
    assert title == "日内模拟平仓 · 做多 NVDA.US +3.50%"
    assert "✅ **日内模拟平仓 · 做多 NVDA.US（英伟达）**" in content
    assert "145.20 → 150.28（**+3.50%**）" in content
    assert "42分15秒" in content
    assert "估算标注" not in content

    est_title, est_content = render_trade_notification(_exit_event(return_pct=-1.25, estimated=True))
    assert est_title == "日内模拟平仓（估算） · 做多 NVDA.US -1.25%"
    assert "⚠️ **日内模拟平仓（估算） · 做多 NVDA.US**" in est_content
    assert "估算标注：截止行情缺失或重启后补记" in est_content
    assert "计划清仓：15:50:00 美东 / 04:50:00 北京" in est_content


def test_notify_trade_events_filters_non_trade_events_and_uses_alert_route():
    calls = []

    class FakeNotifier:
        def send(self, content, **kwargs):
            calls.append((content, kwargs))
            return NotificationResult(notification_id=len(calls), push_attempted=True, push_sent=True)

    events = [
        {"kind": "confirmed", "symbol": "NVDA.US", "evidence": {}},
        {"kind": "hold", "symbol": "NVDA.US", "trade_id": "t1"},
        {"kind": "data", "symbol": "NVDA.US", "issue": "报价延迟"},
        _entry_event(),
        _exit_event(estimated=True),
    ]
    assert [is_trade_event(e) for e in events] == [False, False, False, True, True]

    sent = notify_trade_events(
        events,
        notifier_factory=FakeNotifier,
        names_loader=lambda symbols: {"NVDA.US": "英伟达"},
    )
    assert sent == 2
    assert len(calls) == 2

    entry_content, entry_kwargs = calls[0]
    assert "日内模拟开仓" in entry_content
    assert entry_kwargs["route_type"] == "alert"
    assert entry_kwargs["severity"] == "info"
    assert entry_kwargs["uid"] is None
    assert entry_kwargs["dedup_key"] == f"intraday-simulation:entry:{events[3]['trade_id']}"
    assert entry_kwargs["cooldown_key"] == entry_kwargs["dedup_key"]
    assert entry_kwargs["title"].startswith("日内模拟开仓")

    exit_content, exit_kwargs = calls[1]
    assert "日内模拟平仓（估算）" in exit_content
    assert exit_kwargs["route_type"] == "alert"
    assert exit_kwargs["severity"] == "warning"
    assert exit_kwargs["dedup_key"] == f"intraday-simulation:exit:{events[4]['trade_id']}"


def test_notify_trade_events_respects_env_disable_and_fail_open(monkeypatch):
    calls = []

    class FakeNotifier:
        def send(self, content, **kwargs):
            calls.append(kwargs["dedup_key"])
            if len(calls) == 1:
                raise RuntimeError("telegram timeout")
            return NotificationResult(notification_id=2, push_attempted=True, push_sent=True)

    monkeypatch.setenv("INTRADAY_TRADE_NOTIFICATIONS", "false")
    assert notify_trade_events([_entry_event()], notifier_factory=FakeNotifier, names_loader=lambda _: {}) == 0
    assert calls == []

    monkeypatch.setenv("INTRADAY_TRADE_NOTIFICATIONS", "true")

    def broken_names(_symbols):
        raise RuntimeError("db temporarily down")

    sent = notify_trade_events(
        [_entry_event(), _exit_event()],
        notifier_factory=FakeNotifier,
        names_loader=broken_names,
    )
    assert sent == 1
    assert len(calls) == 2


def test_end_to_end_notification_service_persists_global_row_and_posts_telegram(monkeypatch):
    reset_notification_noise_state()
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Notification.__table__.create(engine)

    class TempDB:
        @contextmanager
        def get_session(self):
            with Session(engine, expire_on_commit=False) as session:
                yield session

        def _run_write_transaction(self, name, callback):
            with self.get_session() as session, session.begin():
                return callback(session)

    repo = NotificationRepository(TempDB())
    config = NotificationConfig(telegram_bot_token="bot-token", telegram_chat_id="chat-42")
    monkeypatch.setattr("finance_analysis.notification.service.get_notification_config", lambda: config)
    monkeypatch.setattr("finance_analysis.database.repositories.notification.NotificationRepository", lambda: repo)

    posted = []

    def fake_post(url, json=None, timeout=None, **kwargs):
        posted.append((url, json))
        return Mock(status_code=200, json=lambda: {"ok": True}, text='{"ok": true}')

    monkeypatch.setattr("finance_analysis.notification.senders.telegram.requests.post", fake_post)
    try:
        sent = notify_trade_events(
            [_entry_event(), _exit_event()],
            notifier_factory=NotificationService,
            names_loader=lambda _: {"NVDA.US": "英伟达"},
        )
        assert sent == 2
        assert len(posted) == 2
        assert posted[0][0] == "https://api.telegram.org/botbot-token/sendMessage"
        assert posted[0][1]["chat_id"] == "chat-42"
        assert posted[0][1]["parse_mode"] == "Markdown"
        assert "*日内模拟开仓 · 做多 NVDA.US（英伟达）*" in posted[0][1]["text"]
        assert "\\(" not in posted[0][1]["text"]
        assert "*日内模拟平仓 · 做多 NVDA.US（英伟达）*" in posted[1][1]["text"]

        listed = repo.list_messages(uid=99)
        assert listed["total"] == 2
        assert all(item["uid"] is None and item["route_type"] == "alert" for item in listed["items"])
    finally:
        reset_notification_noise_state()
        engine.dispose()


def test_scheduler_dispatches_committed_trade_notifications_without_blocking_redis(monkeypatch):
    async def run_case():
        redis = FakeRedis()
        repo = RealtimeStateRepository(redis)
        now = datetime(2026, 11, 20, 14, 41, 5, tzinfo=timezone.utc)
        await repo.write_quote(
            QuoteState(
                "NVDA.US",
                trading_date=now.date(),
                last_price=Decimal("145.20"),
                event_time=now - timedelta(seconds=2),
                received_at=now,
            )
        )
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()
        dispatched = []
        entry = _entry_event()
        retired_exit = _exit_event(return_pct=1.80)
        retired_exit["symbol"] = "TQQQ.US"
        retired_exit["trade"]["symbol"] = "TQQQ.US"

        def fake_process_with_events(symbol, result, quote, when):
            if symbol == "NVDA.US":
                return {"symbol": symbol, "position": entry["trade"]}, [
                    {"kind": "confirmed", "symbol": symbol},
                    entry,
                ]
            if symbol == "TQQQ.US":
                return {"symbol": symbol, "position": None}, [retired_exit]
            return {"symbol": symbol, "position": None}, []

        def fake_notify(events):
            dispatched.extend(events)
            if len(dispatched) >= 2:
                loop.call_soon_threadsafe(stop_event.set)
            return len(events)

        monkeypatch.setattr(scheduler, "SYMBOLS", ("NVDA.US",))
        monkeypatch.setattr(scheduler, "open_retired_symbols", lambda: {"TQQQ.US"})
        monkeypatch.setattr(scheduler, "process_with_events", fake_process_with_events)
        monkeypatch.setattr(scheduler, "notify_trade_events", fake_notify)
        monkeypatch.setattr(scheduler, "utc_now", lambda: now)

        await asyncio.wait_for(scheduler.run(repo, {}, stop_event), timeout=3)

        assert [e["kind"] for e in dispatched] == ["entry", "exit"] or [e["kind"] for e in dispatched] == ["exit", "entry"]
        assert {e["symbol"] for e in dispatched} == {"NVDA.US", "TQQQ.US"}
        nvda_state = json.loads(await repo.redis.get("rt:intraday-simulation:NVDA.US"))
        assert nvda_state["position"]["symbol"] == "NVDA.US"

    asyncio.run(run_case())


def test_scheduler_does_not_notify_when_process_raises_and_survives_notify_failure(monkeypatch):
    async def run_case():
        redis = FakeRedis()
        repo = RealtimeStateRepository(redis)
        now = datetime(2026, 11, 20, 14, 41, 5, tzinfo=timezone.utc)
        loop = asyncio.get_running_loop()
        stop_event = asyncio.Event()
        notified = []

        def failing_process(symbol, result, quote, when):
            loop.call_soon_threadsafe(stop_event.set)
            raise RuntimeError("db rollback")

        monkeypatch.setattr(scheduler, "SYMBOLS", ("NVDA.US",))
        monkeypatch.setattr(scheduler, "open_retired_symbols", lambda: set())
        monkeypatch.setattr(scheduler, "process_with_events", failing_process)
        monkeypatch.setattr(scheduler, "notify_trade_events", lambda batch: notified.extend(batch))
        monkeypatch.setattr(scheduler, "utc_now", lambda: now)

        from tests.intraday_options.test_scoring import candles
        from finance_analysis.intraday_options.runtime import result_key
        quotes = candles([.001] * 10, symbol="NVDA.US", start=now.replace(minute=30, second=0))
        await asyncio.wait_for(scheduler.run(repo, {"NVDA.US": quotes}, stop_event), timeout=3)
        assert await repo.redis.get(result_key("NVDA.US"))
        assert await repo.redis.get("rt:intraday-simulation:NVDA.US") is None
        assert notified == []

        # Second check: notification failure must not prevent Redis state write or clean shutdown.
        stop_event2 = asyncio.Event()
        entry = _entry_event()

        def ok_process(symbol, result, quote, when):
            return {"symbol": symbol, "position": entry["trade"]}, [entry]

        def failing_notify(batch):
            loop.call_soon_threadsafe(stop_event2.set)
            raise RuntimeError("telegram unreachable")

        monkeypatch.setattr(scheduler, "process_with_events", ok_process)
        monkeypatch.setattr(scheduler, "notify_trade_events", failing_notify)

        await asyncio.wait_for(scheduler.run(repo, {}, stop_event2), timeout=3)
        nvda_state = json.loads(await repo.redis.get("rt:intraday-simulation:NVDA.US"))
        assert nvda_state["position"]["symbol"] == "NVDA.US"

    asyncio.run(run_case())


def test_process_with_events_commits_skips_stale_and_propagates_rollback(monkeypatch):
    from finance_analysis.database.repositories import intraday_simulation as store

    saved = {}
    added = []
    commit_state = {"committed": False}

    class FakeSession:
        def execute(self, *_args, **_kwargs):
            return None

        def get(self, model, key):
            return saved.get((model.__name__, key))

        def add(self, obj):
            added.append(obj)
            if obj.__class__.__name__ == "IntradaySimulationState":
                saved[("IntradaySimulationState", obj.symbol)] = obj

    @contextmanager
    def fake_session_scope():
        commit_state["committed"] = False
        yield FakeSession()
        commit_state["committed"] = True

    monkeypatch.setattr(
        store.DatabaseManager, "get_instance", lambda: SimpleNamespace(session_scope=fake_session_scope)
    )
    entry = _entry_event()
    now = datetime(2026, 11, 20, 14, 41, 5, tzinfo=timezone.utc)
    monkeypatch.setattr(
        store,
        "transition",
        lambda previous, symbol, result, quote, when: (
            {"symbol": symbol, "calculated_at": when.isoformat(), "position": entry["trade"]},
            [entry],
        ),
    )

    state, events = store.process_with_events("NVDA.US", None, None, now)
    assert commit_state["committed"] is True
    assert state["position"]["symbol"] == "NVDA.US"
    assert events == [entry]

    # Same or older timestamp skips transition and emits zero events.
    same_state, stale_events = store.process_with_events("NVDA.US", None, None, now)
    assert same_state["position"]["symbol"] == "NVDA.US"
    assert stale_events == []

    # Rollback inside transaction raises before returning any events.
    def broken_transition(*_args):
        return {"symbol": "NVDA.US", "calculated_at": (now + timedelta(seconds=5)).isoformat()}, [
            {"kind": "exit", "trade_id": "missing", "trade": {}}
        ]

    monkeypatch.setattr(store, "transition", broken_transition)
    with pytest.raises(AttributeError):
        store.process_with_events("NVDA.US", None, None, now + timedelta(seconds=5))
    assert commit_state["committed"] is False


def test_real_v7_transition_events_render_and_notify_cleanly():
    from finance_analysis.intraday_options.rules import StartPolicy
    from tests.intraday_options.historical import historical_signal
    from finance_analysis.intraday_options.simulation import transition
    from finance_analysis.intraday_options.structure import execution_context
    from tests.intraday_options.test_simulation import quote
    from tests.intraday_options.test_v7_optimization import V7_POLICY, _make_bars, _make_peer_pool

    vals8 = [100.0 + x for x in (0.0, 0.35, 0.70, 1.05, 1.40, 1.80, 2.20, 2.60)]
    nvda8 = _make_bars(vals8, symbol="NVDA.US", wick=Decimal("0.01"))
    spy_ok = _make_bars([500.0 + x for x in (0.0, 0.15, 0.30, 0.45, 0.60, 0.75, 0.90, 1.05)], symbol="SPY.US")
    peers = _make_peer_pool(nvda8, side=1, nvda_rank=1, breadth_ratio=0.75, count=12)
    t_entry = nvda8[-1].bar_time + timedelta(minutes=1, seconds=5)
    base8 = historical_signal("v7", 1)
    res = {**base8, **execution_context(nvda8, spy_ok, peer_bars=peers, settings=V7_POLICY)}
    entry_price = 102.65
    state, entry_events = transition({}, "NVDA.US", res, quote(t_entry, entry_price), t_entry, settings=V7_POLICY)
    assert any(e["kind"] == "entry" for e in entry_events)

    # Trigger V7 +3.5% take profit on a later tick.
    t_exit = t_entry + timedelta(minutes=15)
    state, exit_events = transition(state, "NVDA.US", res, quote(t_exit, 106.30), t_exit, settings=V7_POLICY)
    assert any(e["kind"] == "exit" for e in exit_events)
    assert isinstance(V7_POLICY, StartPolicy)

    sent_payloads = []

    class FakeNotifier:
        def send(self, content, **kwargs):
            sent_payloads.append((content, kwargs))
            return NotificationResult(notification_id=len(sent_payloads), push_attempted=True, push_sent=True)

    assert (
        notify_trade_events(
            [*entry_events, *exit_events],
            notifier_factory=FakeNotifier,
            names_loader=lambda _: {"NVDA.US": "英伟达"},
        )
        == 2
    )
    assert len(sent_payloads) == 2
    entry_body, entry_meta = sent_payloads[0]
    exit_body, exit_meta = sent_payloads[1]
    assert "日内模拟开仓 · 做多 NVDA.US" in entry_meta["title"]
    assert "开盘区间突破" in entry_body
    assert "102.65" in entry_body
    assert "日内模拟平仓 · 做多 NVDA.US" in exit_meta["title"]
    assert "到达波段止盈目标" in exit_body
    assert "_" not in entry_body and "_" not in exit_body
    assert "(" not in entry_body and ")" not in entry_body
    assert "(" not in exit_body and ")" not in exit_body


def test_render_handles_non_finite_values_breakeven_and_markdown_chars():
    event = _exit_event(return_pct=-0.0, estimated=False)
    event["trade"]["duration_seconds"] = float("nan")
    event["trade"]["exit_reason"] = "测试_原因*带`符号`(ok)"
    title, content = render_trade_notification(event, symbol_name="Tech *ETF* [3x]_test")
    assert "0.00%" in title and "-0.00%" not in title
    assert "➖ **日内模拟平仓 · 做多 NVDA.US（Tech ＊ETF＊ 【3x】 test）**" in content
    assert "持仓时长：—" in content
    assert "_" not in content and "`" not in content
    assert "(" not in content and ")" not in content

    bad_entry = _entry_event()
    bad_entry["trade"]["entry_price"] = float("nan")
    bad_entry["trade"]["invalidation"] = "bad"
    bad_entry["trade"]["target"] = float("inf")
    bad_title, bad_content = render_trade_notification(bad_entry)
    assert "@ —" in bad_title
    assert "进场价格：—" in bad_content


def test_notify_trade_events_factory_failure_is_fail_open_and_persistence_warning(caplog):
    assert (
        notify_trade_events(
            [_entry_event()],
            notifier_factory=lambda: (_ for _ in ()).throw(RuntimeError("config error")),
            names_loader=lambda _: {},
        )
        == 0
    )

    class PushOnlyNotifier:
        def send(self, content, **kwargs):
            return NotificationResult(notification_id=None, push_attempted=True, push_sent=True)

    with caplog.at_level("WARNING"):
        assert (
            notify_trade_events(
                [_entry_event()],
                notifier_factory=PushOnlyNotifier,
                names_loader=lambda _: {"NVDA.US": "英伟达"},
            )
            == 1
        )
    assert "未能写入 notification" in caplog.text




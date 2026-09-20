"""exit_v1 hard stop, stages, ADDON-first reduce, soft-episode dedupe, recovery."""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bar_fixtures import recover_last_adjacent, session_bars, trading_dates, weaken_last_adjacent  # noqa: E402

from finance_analysis.portfolio.models import ResolvedLot, ResolvedPosition  # pragma: allowlist secret
from finance_analysis.trade_engine.bars import latest_expected_closed  # pragma: allowlist secret
from finance_analysis.trade_engine.config import RiskPolicy  # pragma: allowlist secret
from finance_analysis.trade_engine.models import MarketContext, QuoteView  # pragma: allowlist secret
from finance_analysis.trade_engine.strategies.exit_v1 import ExitV1  # pragma: allowlist secret

SH = ZoneInfo("Asia/Shanghai")
DAY = datetime(2026, 9, 16, tzinfo=SH).date()
POLICY = RiskPolicy()


def _bars(*, until, close=Decimal("100"), high_close=None, days=3):
    dates = trading_dates("CN", until.date(), count=days)
    return session_bars(days=dates, close=close, until=until, high_close=high_close, high_on=until.date())


def _position(core_qty="1000", addon_qty="500", *, core_entry=None, addon_entry=None, core_price="100", addon_price="100"):
    core_time = core_entry or datetime(2026, 9, 16, 9, 30, tzinfo=SH)
    lots = [
        ResolvedLot("core", "CORE", Decimal(core_qty), Decimal(core_price), core_time),
    ]
    if addon_qty:
        lots.append(
            ResolvedLot(
                "addon",
                "ADDON",
                Decimal(addon_qty),
                Decimal(addon_price),
                addon_entry or core_time + timedelta(minutes=5),
            )
        )
    return ResolvedPosition(
        source="DB",
        coverage="DB",
        uid=1,
        market="CN",
        account_id="1",
        position_id="11",
        symbol="600519.SH",
        asset_type="STOCK",
        quantity=sum((lot.quantity for lot in lots), start=Decimal("0")),
        average_cost=Decimal(core_price),
        lots=tuple(lots),
    )


def _run(position, *, quote, bars, state=None, now, latest_expected=None):
    strategy = ExitV1()
    payload = {} if state is None else state
    context = MarketContext(market="CN", as_of=now, trading_date=now, session_open=True)
    signals = strategy.evaluate(
        position,
        context,
        quote,
        bars,
        payload,
        policy=POLICY,
        now=now,
        latest_expected=latest_expected,
    )
    return signals, payload


def _action(signals):
    persistable = [item for item in signals if item.evidence.get("persist") is not False]
    return persistable[0] if persistable else signals[0]


def test_hard_stop_uses_quote_and_does_not_need_5m():
    now = datetime(2026, 9, 16, 10, 0, tzinfo=SH)
    signals, state = _run(
        _position(addon_qty=None),
        quote=QuoteView(price=Decimal("96"), quote_as_of=now, valid=True),
        bars=[],
        now=now,
    )
    signal = _action(signals)
    assert signal.action == "EXIT"
    assert signal.suggested_target_quantity == Decimal("0")
    assert Decimal(str(state.get("last_hard_target"))) == Decimal("0")


def test_stale_quote_does_not_fire_hard_stop():
    now = datetime(2026, 9, 16, 10, 0, tzinfo=SH)
    signals, _state = _run(
        _position(addon_qty=None),
        quote=QuoteView(price=Decimal("1"), quote_as_of=now - timedelta(minutes=10), valid=False, stale=True),
        bars=[],
        now=now,
    )
    assert all(item.action != "EXIT" for item in signals)


def test_soft_reduce_then_same_episode_does_not_rehalve():
    now = datetime(2026, 9, 16, 14, 0, tzinfo=SH)
    bars = weaken_last_adjacent(_bars(until=now, high_close=Decimal("110")))
    quote = QuoteView(price=Decimal("108"), quote_as_of=now, valid=True)
    first, state = _run(
        _position(addon_qty=None),
        quote=quote,
        bars=bars,
        now=now,
        latest_expected=latest_expected_closed("CN", now),
    )
    signal = _action(first)
    assert signal.action == "REDUCE"
    assert signal.suggested_target_quantity == Decimal("500")
    later = now + timedelta(minutes=10)
    again, _ = _run(
        _position(addon_qty=None),
        quote=QuoteView(price=Decimal("108"), quote_as_of=later, valid=True),
        bars=weaken_last_adjacent(_bars(until=later)),
        state=state,
        now=later,
        latest_expected=latest_expected_closed("CN", later),
    )
    persistable = [item for item in again if item.action in {"REDUCE", "EXIT"} and item.evidence.get("persist") is not False]
    assert persistable == [] or Decimal(str(persistable[0].suggested_target_quantity)) == Decimal("500")
    assert Decimal(str(state.get("last_soft_target"))) == Decimal("500")


def test_addon_stage_a_failure_clears_addon_only():
    now = datetime(2026, 9, 16, 14, 0, tzinfo=SH)
    bars = weaken_last_adjacent(_bars(until=now, high_close=Decimal("110")))
    signals, _state = _run(
        _position(
            core_qty="1000",
            addon_qty="500",
            core_entry=datetime(2026, 9, 14, 9, 35, tzinfo=SH),
            addon_entry=datetime(2026, 9, 16, 9, 40, tzinfo=SH),
            core_price="100",
            addon_price="110",
        ),
        quote=QuoteView(price=Decimal("108"), quote_as_of=now, valid=True),
        bars=bars,
        now=now,
        latest_expected=latest_expected_closed("CN", now),
    )
    signal = _action(signals)
    assert signal.action == "REDUCE"
    assert signal.suggested_target_quantity == Decimal("1000")


def test_recovery_allows_new_episode_on_current_quantity():
    now = datetime(2026, 9, 16, 14, 0, tzinfo=SH)
    bars = weaken_last_adjacent(_bars(until=now, high_close=Decimal("110")))
    quote = QuoteView(price=Decimal("108"), quote_as_of=now, valid=True)
    _first, state = _run(
        _position(addon_qty=None),
        quote=quote,
        bars=bars,
        now=now,
        latest_expected=latest_expected_closed("CN", now),
    )
    recovered_at = now + timedelta(minutes=20)
    _recovered, state = _run(
        _position(core_qty="500", addon_qty=None),
        quote=QuoteView(price=Decimal("108"), quote_as_of=recovered_at, valid=True),
        bars=recover_last_adjacent(_bars(until=recovered_at, high_close=Decimal("110"))),
        state=state,
        now=recovered_at,
        latest_expected=latest_expected_closed("CN", recovered_at),
    )
    assert state.get("soft_episode_active") is False
    weak_again_at = now + timedelta(minutes=30)
    second, _ = _run(
        _position(core_qty="500", addon_qty=None),
        quote=QuoteView(price=Decimal("108"), quote_as_of=weak_again_at, valid=True),
        bars=weaken_last_adjacent(_bars(until=weak_again_at, high_close=Decimal("110"))),
        state=state,
        now=weak_again_at,
        latest_expected=latest_expected_closed("CN", weak_again_at),
    )
    signal = _action(second)
    assert signal.action == "REDUCE"
    assert signal.suggested_target_quantity == Decimal("250")

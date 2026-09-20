"""exit_v1 quote vs daily-formed stops. No 5m soft weakness."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from finance_analysis.portfolio.models import ResolvedLot, ResolvedPosition  # pragma: allowlist secret
from finance_analysis.trade_engine.config import RiskPolicy  # pragma: allowlist secret
from finance_analysis.trade_engine.models import DailyBar, PositionContext, QuoteView  # pragma: allowlist secret
from finance_analysis.trade_engine.strategies.exit_v1 import ExitV1  # pragma: allowlist secret

SH = ZoneInfo("Asia/Shanghai")
POLICY = RiskPolicy()


def _bars(closes):
    start = date(2026, 6, 1)
    rows = []
    day = start
    for close in closes:
        while day.weekday() >= 5:
            day += timedelta(days=1)
        price = Decimal(str(close))
        rows.append(DailyBar(day, price, price + Decimal("1"), price - Decimal("1"), price, 1000))
        day += timedelta(days=1)
    return rows


def _position(core_qty="1000", addon_qty=None, *, core_price="100", addon_price="110"):
    core_time = datetime(2026, 6, 2, 9, 30, tzinfo=SH)
    lots = [ResolvedLot("core", "CORE", Decimal(core_qty), Decimal(core_price), core_time)]
    if addon_qty:
        lots.append(
            ResolvedLot(
                "addon",
                "ADDON",
                Decimal(addon_qty),
                Decimal(addon_price),
                datetime(2026, 7, 1, 9, 30, tzinfo=SH),
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


def _run(position, *, quote, bars, state=None, now=None):
    strategy = ExitV1()
    payload = {} if state is None else state
    context = PositionContext(
        market="CN",
        symbol=position.symbol,
        position=position,
        quote=quote,
        daily_bars=bars,
        strategy_state=payload,
        now=now or datetime(2026, 9, 16, 10, 0, tzinfo=SH),
        policy=POLICY,
    )
    return strategy.evaluate(context), payload


def test_capital_stop_uses_quote_and_does_not_need_5m():
    now = datetime(2026, 9, 16, 10, 0, tzinfo=SH)
    signals, state = _run(
        _position(addon_qty=None),
        quote=QuoteView(price=Decimal("95"), quote_as_of=now, valid=True),
        bars=_bars([100] * 30),
        now=now,
    )
    assert len(signals) == 1
    assert signals[0].action == "EXIT"
    assert signals[0].suggested_target_quantity == Decimal("0")
    assert state.get("profit_stage") in {"A", "UNKNOWN"}


def test_stale_quote_does_not_fire_stop():
    now = datetime(2026, 9, 16, 10, 0, tzinfo=SH)
    signals, _state = _run(
        _position(addon_qty=None),
        quote=QuoteView(price=Decimal("1"), quote_as_of=now - timedelta(minutes=10), valid=False, stale=True),
        bars=_bars([100] * 10),
        now=now,
    )
    assert signals == []


def test_addon_stop_reduce_keeps_core():
    now = datetime(2026, 9, 16, 10, 0, tzinfo=SH)
    bars = _bars([100] * 20 + [110] * 10)
    position = _position(core_qty="1000", addon_qty="500")
    first, state = _run(
        position,
        quote=QuoteView(price=Decimal("108"), quote_as_of=now, valid=True),
        bars=bars,
        now=now,
    )
    assert first == []
    addon_stop = Decimal(str(state["lots"]["addon"]["active_stop"]))
    hit = now + timedelta(minutes=5)
    signals, _ = _run(
        position,
        quote=QuoteView(price=addon_stop, quote_as_of=hit, valid=True),
        bars=bars,
        state=state,
        now=hit,
    )
    assert len(signals) == 1
    assert signals[0].action == "REDUCE"
    assert signals[0].suggested_target_quantity == Decimal("1000")


def test_all_lots_stopped_emit_exit():
    now = datetime(2026, 9, 16, 10, 0, tzinfo=SH)
    signals, _state = _run(
        _position(core_qty="1000", addon_qty="500"),
        quote=QuoteView(price=Decimal("1"), quote_as_of=now, valid=True),
        bars=_bars([100] * 30),
        now=now,
    )
    assert signals[0].action == "EXIT"
    assert signals[0].suggested_target_quantity == Decimal("0")


def test_same_stop_episode_cools_down_then_reviews_again():
    now = datetime(2026, 9, 16, 10, 0, tzinfo=SH)
    position = _position(addon_qty=None)
    first, state = _run(
        position,
        quote=QuoteView(price=Decimal("95"), quote_as_of=now, valid=True),
        bars=_bars([100] * 20),
        now=now,
    )
    assert first[0].action == "EXIT"
    state["exit_review_at"] = now.isoformat()
    state["exit_review_key"] = first[0].proposal_key
    later = now + timedelta(minutes=5)
    again, _ = _run(
        position,
        quote=QuoteView(price=Decimal("95"), quote_as_of=later, valid=True),
        bars=_bars([100] * 20),
        state=state,
        now=later,
    )
    assert again == []
    reopened = now + timedelta(minutes=31)
    third, _ = _run(
        position,
        quote=QuoteView(price=Decimal("95"), quote_as_of=reopened, valid=True),
        bars=_bars([100] * 20),
        state=state,
        now=reopened,
    )
    assert len(third) == 1
    assert third[0].proposal_key == first[0].proposal_key


def test_confirmed_exit_episode_stays_resolved():
    now = datetime(2026, 9, 16, 10, 0, tzinfo=SH)
    position = _position(addon_qty=None)
    first, state = _run(
        position,
        quote=QuoteView(price=Decimal("95"), quote_as_of=now, valid=True),
        bars=_bars([100] * 20),
        now=now,
    )
    state["resolved_proposal_keys"] = [first[0].proposal_key]
    later = now + timedelta(minutes=31)
    again, _ = _run(
        position,
        quote=QuoteView(price=Decimal("95"), quote_as_of=later, valid=True),
        bars=_bars([100] * 20),
        state=state,
        now=later,
    )
    assert again == []


def test_no_intraday_watch_from_ordinary_quote_move():
    now = datetime(2026, 9, 16, 10, 0, tzinfo=SH)
    signals, _state = _run(
        _position(addon_qty=None),
        quote=QuoteView(price=Decimal("99"), quote_as_of=now, valid=True),
        bars=_bars([100] * 20),
        now=now,
    )
    assert signals == []

"""exit_v1 quote vs daily-formed stops. Stateless: same input repeats the same REDUCE."""

from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from finance_analysis.portfolio.models import ResolvedLot, ResolvedPosition  # pragma: allowlist secret
from finance_analysis.trade_engine.config import RiskPolicy  # pragma: allowlist secret
from finance_analysis.trade_engine.models import DailyBar, PositionContext, QuoteView  # pragma: allowlist secret
from finance_analysis.trade_engine.position_risk import compute_position_risk  # pragma: allowlist secret
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


def _run(position, *, quote, bars, now=None):
    now = now or datetime(2026, 9, 16, 10, 0, tzinfo=SH)
    risk = compute_position_risk(position, bars, POLICY)
    context = PositionContext(
        market="CN",
        symbol=position.symbol,
        position=position,
        quote=quote,
        daily_bars=bars,
        risk=risk,
        now=now,
        policy=POLICY,
    )
    return ExitV1().evaluate(context), risk


def test_capital_stop_uses_quote_and_does_not_need_5m():
    now = datetime(2026, 9, 16, 10, 0, tzinfo=SH)
    signals, risk = _run(
        _position(addon_qty=None),
        quote=QuoteView(price=Decimal("95"), quote_as_of=now, valid=True),
        bars=_bars([100] * 30),
        now=now,
    )
    assert len(signals) == 1
    assert signals[0].action == "EXIT"
    assert signals[0].suggested_target_quantity == Decimal("0")
    assert risk.profit_stage in {"A", "UNKNOWN"}


def test_stale_quote_does_not_fire_stop():
    now = datetime(2026, 9, 16, 10, 0, tzinfo=SH)
    signals, _risk = _run(
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
    first, risk = _run(position, quote=QuoteView(price=Decimal("108"), quote_as_of=now, valid=True), bars=bars, now=now)
    assert first == []
    addon = next(item for item in risk.lots if item.lot_id == "addon")
    hit = now + timedelta(minutes=5)
    signals, _ = _run(position, quote=QuoteView(price=addon.active_stop, quote_as_of=hit, valid=True), bars=bars, now=hit)
    assert len(signals) == 1
    assert signals[0].action == "REDUCE"
    assert signals[0].suggested_target_quantity == Decimal("1000")


def test_all_lots_stopped_emit_exit():
    now = datetime(2026, 9, 16, 10, 0, tzinfo=SH)
    signals, _risk = _run(
        _position(core_qty="1000", addon_qty="500"),
        quote=QuoteView(price=Decimal("1"), quote_as_of=now, valid=True),
        bars=_bars([100] * 30),
        now=now,
    )
    assert signals[0].action == "EXIT"
    assert signals[0].suggested_target_quantity == Decimal("0")


def test_same_input_repeats_reduce_three_times():
    now = datetime(2026, 9, 16, 10, 0, tzinfo=SH)
    bars = _bars([100] * 20 + [110] * 10)
    position = _position(core_qty="1000", addon_qty="500")
    _, risk = _run(position, quote=QuoteView(price=Decimal("108"), quote_as_of=now, valid=True), bars=bars, now=now)
    addon = next(item for item in risk.lots if item.lot_id == "addon")
    quote = QuoteView(price=addon.active_stop, quote_as_of=now, valid=True)
    first, _ = _run(position, quote=quote, bars=bars, now=now)
    second, _ = _run(position, quote=quote, bars=bars, now=now + timedelta(minutes=30))
    third, _ = _run(position, quote=quote, bars=bars, now=now + timedelta(minutes=60))
    assert [item[0].action for item in (first, second, third)] == ["REDUCE", "REDUCE", "REDUCE"]
    assert [item[0].suggested_target_quantity for item in (first, second, third)] == [Decimal("1000")] * 3


def test_same_input_repeats_exit_three_times():
    now = datetime(2026, 9, 16, 10, 0, tzinfo=SH)
    position = _position(addon_qty=None)
    quote = QuoteView(price=Decimal("95"), quote_as_of=now, valid=True)
    bars = _bars([100] * 20)
    first, _ = _run(position, quote=quote, bars=bars, now=now)
    second, _ = _run(position, quote=quote, bars=bars, now=now + timedelta(minutes=30))
    third, _ = _run(position, quote=quote, bars=bars, now=now + timedelta(minutes=60))
    assert [item[0].action for item in (first, second, third)] == ["EXIT", "EXIT", "EXIT"]
    assert [item[0].suggested_target_quantity for item in (first, second, third)] == [Decimal("0")] * 3


def test_no_intraday_watch_from_ordinary_quote_move():
    now = datetime(2026, 9, 16, 10, 0, tzinfo=SH)
    signals, _risk = _run(
        _position(addon_qty=None),
        quote=QuoteView(price=Decimal("99"), quote_as_of=now, valid=True),
        bars=_bars([100] * 20),
        now=now,
    )
    assert signals == []

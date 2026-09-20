"""add_v1 medium-term ADD setups, gates, sizing and daily dedupe."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from finance_analysis.portfolio.models import ResolvedLot, ResolvedPosition  # pragma: allowlist secret
from finance_analysis.trade_engine.config import RiskPolicy  # pragma: allowlist secret
from finance_analysis.trade_engine.models import DailyBar, PositionContext, PositionRisk, LotRisk, QuoteView  # pragma: allowlist secret
from finance_analysis.trade_engine.strategies.add_v1 import AddV1, BREAKOUT, PULLBACK  # pragma: allowlist secret

NOW = datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc)
POLICY = RiskPolicy()


def _bars(closes, volumes=None, start=date(2026, 6, 1), width=Decimal("3")):
    rows = []
    day = start
    for index, close in enumerate(closes):
        while day.weekday() >= 5:
            day += timedelta(days=1)
        price = Decimal(str(close))
        volume = 1000
        if volumes is not None:
            volume = volumes[index]
        rows.append(DailyBar(day, price, price + width, price - width, price, volume))
        day += timedelta(days=1)
    return rows


def _trend(n=40, start=100, step=0.2):
    return [start + i * step for i in range(n)]


def _position(*, quantity="1000", cost="100", source="DB", had_addon=False):
    return ResolvedPosition(
        source=source,  # type: ignore[arg-type]
        coverage="DB",
        uid=1,
        market="CN",
        account_id="1",
        position_id="11",
        symbol="600519.SH",
        asset_type="STOCK",
        quantity=Decimal(quantity),
        average_cost=Decimal(cost),
        lots=(ResolvedLot("core", "CORE", Decimal(quantity), Decimal(cost), NOW),),
        had_addon=had_addon,
    )


def _risk(*, stage="A", stop="106"):
    return PositionRisk(
        lots=(
            LotRisk(
                "core",
                "CORE",
                Decimal("1000"),
                Decimal("100"),
                Decimal("108"),
                stage,
                Decimal(stop),
                Decimal("95"),
            ),
        ),
        profit_stage=stage,
        active_stop=Decimal(stop),
        high_watermark=Decimal("108"),
    )


def _run(bars, *, position=None, risk=None, state=None, cash="1000000", nav="2000000", now=NOW):
    position = position or _position()
    ctx = PositionContext(
        market="CN",
        symbol=position.symbol,
        position=position,
        quote=QuoteView(bars[-1].close, now, True),
        daily_bars=bars,
        strategy_state={} if state is None else state,
        risk=risk or _risk(),
        now=now,
        policy=POLICY,
        cash=Decimal(cash),
        market_nav=Decimal(nav),
        position_value=position.quantity * bars[-1].close,
    )
    return AddV1().evaluate(ctx), ctx.strategy_state


def _breakout_bars():
    body = _trend(36, 100, 0.2)  # last ~107.0
    consol = [107.2, 107.1, 107.3, 107.0, 107.2]
    volumes = [1000] * 36 + [1000] * 5 + [2000]
    return _bars(body + consol + [111.0], volumes=volumes)


def _pullback_bars():
    body = _trend(36, 100, 0.25)  # last ~108.75
    pull = [108.5, 108.2, 108.0]
    volumes = [1000] * 36 + [400, 350, 300, 1200]
    return _bars(body + pull + [112.5], volumes=volumes)


def test_loss_does_not_add():
    bars = _breakout_bars()
    signals, _ = _run(bars, position=_position(cost="200"))
    assert signals == []


def test_one_percent_profit_does_not_add():
    last = _breakout_bars()[-1].close
    cost = format(last / Decimal("1.01"), "f")
    signals, _ = _run(_breakout_bars(), position=_position(cost=cost))
    assert signals == []


def test_stage_c_blocks_add():
    signals, _ = _run(_breakout_bars(), risk=_risk(stage="C"))
    assert signals == []


def test_extension_blocks_add():
    body = _trend(40, 100, 0.2)
    stretched = body[:-1] + [body[-2] + 20]
    signals, _ = _run(_bars(stretched, width=Decimal("0.5")))
    assert signals == []


def test_historical_addon_blocks_second_add():
    signals, _ = _run(_breakout_bars(), position=_position(had_addon=True))
    assert signals == []


def test_google_position_does_not_add():
    signals, _ = _run(_breakout_bars(), position=_position(source="GOOGLE"))
    assert signals == []


def test_breakout_continuation_emits_add():
    signals, _ = _run(_breakout_bars())
    assert len(signals) == 1
    assert signals[0].action == "ADD"
    assert signals[0].evidence["setup"] == BREAKOUT
    assert signals[0].suggested_quantity > 0
    assert signals[0].suggested_target_quantity == Decimal("1000") + signals[0].suggested_quantity


def test_pullback_reentry_emits_add():
    signals, _ = _run(_pullback_bars())
    assert len(signals) == 1
    assert signals[0].action == "ADD"
    assert signals[0].evidence["setup"] == PULLBACK


def test_risk_sizing_takes_the_minimum():
    signals, _ = _run(
        _breakout_bars(),
        cash="55500",
        nav="1110000",
        position=_position(quantity="100"),
        risk=PositionRisk(
            lots=(
                LotRisk("core", "CORE", Decimal("100"), Decimal("100"), Decimal("108"), "A", Decimal("106"), Decimal("95")),
            ),
            profit_stage="A",
            active_stop=Decimal("106"),
        ),
    )
    assert signals
    evidence = signals[0].evidence
    qty_pos = Decimal(str(evidence["qty_by_position"]))
    qty_risk = Decimal(str(evidence["qty_by_risk"]))
    qty_cash = Decimal(str(evidence["qty_by_cash"]))
    assert signals[0].suggested_quantity == min(qty_pos, qty_risk, qty_cash)


def test_add_quantity_uses_tightest_capacity():
    from finance_analysis.trade_engine.daily import legalize_quantity  # pragma: allowlist secret

    assert legalize_quantity(min(Decimal("300"), Decimal("120"), Decimal("500")), "CN") == Decimal("120")


def test_same_daily_bar_does_not_repeat():
    bars = _breakout_bars()
    first, state = _run(bars)
    assert first
    again, _ = _run(bars, state=state)
    assert again == []

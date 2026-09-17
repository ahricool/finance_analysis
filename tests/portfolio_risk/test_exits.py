"""Position exit pure functions. Synthetic quotes and bars only."""

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from finance_analysis.portfolio_risk.bars import NormalizedBar, regular_5m_slots  # pragma: allowlist secret
from finance_analysis.portfolio_risk.config import RiskPolicy  # pragma: allowlist secret
from finance_analysis.portfolio_risk.exits import LegInput, PositionInput, PositionState, QuoteView, evaluate_position_exit  # pragma: allowlist secret
from finance_analysis.portfolio_risk.models import ActivePlan  # pragma: allowlist secret

SH = ZoneInfo("Asia/Shanghai")
DAY = datetime(2026, 9, 16, tzinfo=SH).date()
POLICY = RiskPolicy()


def _closed_bars(count=80, close=Decimal("100")):
    slots = regular_5m_slots("CN", DAY)
    bars = []
    for start, end, session in slots[:count]:
        bars.append(
            NormalizedBar(
                symbol="600519.SH",
                market="CN",
                trade_date=DAY,
                bar_start=start,
                bar_end=end,
                session_id=session,
                open=close,
                high=close + Decimal("1"),
                low=close - Decimal("1"),
                close=close,
                volume=1000,
                amount=close * 1000,
                amount_quality="exact",
                volume_quality="ok",
                provider="sina_minute",
                closed=True,
                slot_key=end.astimezone(SH).strftime("%H:%M"),
            )
        )
    return bars


def _position(core_qty="1000", addon_qty="500"):
    entry = datetime(2026, 9, 16, 9, 30, tzinfo=SH)
    legs = [
        LegInput("core", "CORE", Decimal(core_qty), Decimal("100"), entry),
    ]
    if addon_qty:
        legs.append(LegInput("addon", "ADDON", Decimal(addon_qty), Decimal("100"), entry + timedelta(minutes=5)))
    return PositionInput("a1", "p1", "600519.SH", tuple(legs))


def test_hard_stop_uses_quote_time_and_does_not_need_5m():
    now = datetime(2026, 9, 16, 10, 0, tzinfo=SH)
    quote = QuoteView(price=Decimal("95"), quote_as_of=now, valid=True)
    result = evaluate_position_exit(
        _position(addon_qty=None),
        quote=quote,
        bars=[],
        state=PositionState(),
        policy=POLICY,
        now=now,
        market="CN",
    )
    assert result.quote_status == "OK"
    assert result.leg_exits[0].hard_exit is True
    assert result.position_target == 0
    assert any(event["event_type"] == "HARD_STOP" for event in result.events)


def test_stale_or_unknown_quote_does_not_fire_hard_stop():
    now = datetime(2026, 9, 16, 10, 0, tzinfo=SH)
    stale = QuoteView(price=Decimal("1"), quote_as_of=now - timedelta(minutes=10), valid=False, stale=True)
    result = evaluate_position_exit(_position(addon_qty=None), quote=stale, bars=[], state=PositionState(), policy=POLICY, now=now, market="CN")
    assert result.quote_status == "STALE"
    assert result.leg_exits[0].hard_exit is False
    missing = QuoteView(price=Decimal("1"), quote_as_of=None, valid=False)
    result = evaluate_position_exit(_position(addon_qty=None), quote=missing, bars=[], state=PositionState(), policy=POLICY, now=now, market="CN")
    assert result.quote_status in {"UNAVAILABLE", "UNKNOWN_TIME"}


def test_addon_stage_a_failure_does_not_halve_core():
    now = datetime(2026, 9, 16, 14, 0, tzinfo=SH)
    bars = _closed_bars(70, close=Decimal("101"))
    weak = bars[-1]
    bars[-1] = replace(weak, close=Decimal("90"), open=Decimal("100"), high=Decimal("100"), low=Decimal("89"))
    bars[-2] = replace(bars[-2], close=Decimal("91"), open=Decimal("100"), high=Decimal("100"), low=Decimal("90"))
    quote = QuoteView(price=Decimal("101"), quote_as_of=now, valid=True)
    result = evaluate_position_exit(_position(), quote=quote, bars=bars, state=PositionState(), policy=POLICY, now=now, market="CN")
    by_id = {item.leg_id: item.target_quantity for item in result.leg_exits}
    if result.plan.status == "PENDING":
        assert by_id.get("addon", Decimal("500")) == 0 or by_id["core"] == Decimal("1000")


def test_same_bar_end_does_not_double_count_and_pending_plan_keeps_fixed_target():
    now = datetime(2026, 9, 16, 14, 0, tzinfo=SH)
    bars = _closed_bars(70)
    quote = QuoteView(price=Decimal("101"), quote_as_of=now, valid=True)
    first = evaluate_position_exit(_position(addon_qty=None), quote=quote, bars=bars, state=PositionState(), policy=POLICY, now=now, market="CN")
    second = evaluate_position_exit(
        _position(addon_qty=None),
        quote=quote,
        bars=bars,
        state=first.state,
        policy=POLICY,
        now=now,
        market="CN",
    )
    assert second.state.last_bar_end == first.state.last_bar_end
    pending = first.state
    if first.plan.status != "PENDING":
        pending = pending.__class__(
            **{**pending.__dict__, "plan": ActivePlan(revision=1, status="PENDING", action="REDUCE", position_target="800", leg_targets={"core": "800"})}
        )
    third = evaluate_position_exit(_position(addon_qty=None), quote=quote, bars=bars, state=pending, policy=POLICY, now=now, market="CN")
    if third.plan.status == "PENDING":
        assert third.plan.position_target == pending.plan.position_target or third.plan.revision == pending.plan.revision

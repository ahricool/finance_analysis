"""Position exit pure functions. Synthetic quotes and bars only."""

from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from finance_analysis.portfolio_risk.bars import latest_expected_closed  # pragma: allowlist secret
from finance_analysis.portfolio_risk.config import RiskPolicy  # pragma: allowlist secret
from finance_analysis.portfolio_risk.exits import LegInput, PositionInput, PositionState, QuoteView, evaluate_position_exit  # pragma: allowlist secret
from finance_analysis.portfolio_risk.models import ActivePlan  # pragma: allowlist secret
from bar_fixtures import recover_last_adjacent, session_bars, trading_dates, weaken_last_adjacent

SH = ZoneInfo("Asia/Shanghai")
DAY = datetime(2026, 9, 16, tzinfo=SH).date()
POLICY = RiskPolicy()


def _bars(*, until, close=Decimal("100"), high_close=None, days=3):
    dates = trading_dates("CN", until.date(), count=days)
    return session_bars(days=dates, close=close, until=until, high_close=high_close, high_on=until.date())


def _position(core_qty="1000", addon_qty="500", *, core_entry=None, addon_entry=None, core_price="100", addon_price="100"):
    core_time = core_entry or datetime(2026, 9, 16, 9, 30, tzinfo=SH)
    legs = [LegInput("core", "CORE", Decimal(core_qty), Decimal(core_price), core_time)]
    if addon_qty:
        legs.append(
            LegInput(
                "addon",
                "ADDON",
                Decimal(addon_qty),
                Decimal(addon_price),
                addon_entry or core_time + timedelta(minutes=5),
            )
        )
    return PositionInput("a1", "p1", "600519.SH", tuple(legs))


def test_closed_bars_span_multiple_sessions_and_meet_ema_warmup():
    now = datetime(2026, 9, 16, 14, 0, tzinfo=SH)
    bars = _bars(until=now)
    assert len(bars) >= 60
    assert len({bar.trade_date for bar in bars}) >= 2
    assert all(bar.closed and bar.bar_end <= now for bar in bars)


def test_hard_stop_uses_quote_time_and_does_not_need_5m():
    now = datetime(2026, 9, 16, 10, 0, tzinfo=SH)
    quote = QuoteView(price=Decimal("96"), quote_as_of=now, valid=True)
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
    assert result.plan.status == "PENDING"
    assert result.plan.action == "EXIT"
    assert any(event["event_type"] == "HARD_STOP" for event in result.events)


def test_stale_or_unknown_or_future_quote_does_not_fire_hard_stop():
    now = datetime(2026, 9, 16, 10, 0, tzinfo=SH)
    stale = QuoteView(price=Decimal("1"), quote_as_of=now - timedelta(minutes=10), valid=False, stale=True)
    result = evaluate_position_exit(_position(addon_qty=None), quote=stale, bars=[], state=PositionState(), policy=POLICY, now=now, market="CN")
    assert result.quote_status == "STALE"
    assert result.leg_exits[0].hard_exit is False
    missing = QuoteView(price=Decimal("1"), quote_as_of=None, valid=False)
    result = evaluate_position_exit(_position(addon_qty=None), quote=missing, bars=[], state=PositionState(), policy=POLICY, now=now, market="CN")
    assert result.quote_status in {"UNAVAILABLE", "UNKNOWN_TIME"}
    future = QuoteView(price=Decimal("1"), quote_as_of=now + timedelta(hours=2), valid=True)
    result = evaluate_position_exit(_position(addon_qty=None), quote=future, bars=[], state=PositionState(), policy=POLICY, now=now, market="CN")
    assert result.quote_status == "FUTURE"
    assert result.leg_exits[0].hard_exit is False


def test_hard_stop_upgrades_pending_plan_and_survives_rebound():
    now = datetime(2026, 9, 16, 14, 0, tzinfo=SH)
    bars = weaken_last_adjacent(_bars(until=now, high_close=Decimal("110")))
    quote = QuoteView(price=Decimal("108"), quote_as_of=now, valid=True)
    first = evaluate_position_exit(
        _position(addon_qty=None),
        quote=quote,
        bars=bars,
        state=PositionState(),
        policy=POLICY,
        now=now,
        market="CN",
        latest_expected=latest_expected_closed("CN", now),
    )
    assert first.plan.status == "PENDING"
    assert first.plan.action == "REDUCE"
    assert Decimal(first.plan.position_target) == Decimal("500")
    assert first.events[0]["event_type"] == "CONFIRMED_WEAK"
    hard_time = now + timedelta(minutes=1)
    hard = evaluate_position_exit(
        _position(addon_qty=None),
        quote=QuoteView(price=Decimal("96"), quote_as_of=hard_time, valid=True),
        bars=bars,
        state=first.state,
        policy=POLICY,
        now=hard_time,
        market="CN",
        latest_expected=latest_expected_closed("CN", hard_time),
    )
    assert hard.plan.status == "PENDING"
    assert hard.plan.action == "EXIT"
    assert Decimal(hard.plan.position_target) == Decimal("0")
    assert hard.plan.revision == first.plan.revision + 1
    assert [event["event_type"] for event in hard.events].count("HARD_STOP") == 1
    rebound = evaluate_position_exit(
        _position(addon_qty=None),
        quote=QuoteView(price=Decimal("110"), quote_as_of=hard_time + timedelta(minutes=2), valid=True),
        bars=bars,
        state=hard.state,
        policy=POLICY,
        now=hard_time + timedelta(minutes=2),
        market="CN",
        latest_expected=latest_expected_closed("CN", hard_time + timedelta(minutes=2)),
    )
    assert Decimal(rebound.plan.position_target) == Decimal("0")
    assert rebound.plan.action == "EXIT"
    assert rebound.plan.status == "PENDING"
    assert not any(event["event_type"] == "HARD_STOP" for event in rebound.events)


def test_soft_episode_is_consumed_until_adjacent_recovery():
    now = datetime(2026, 9, 16, 14, 0, tzinfo=SH)
    bars = weaken_last_adjacent(_bars(until=now, high_close=Decimal("110")))
    quote = QuoteView(price=Decimal("108"), quote_as_of=now, valid=True)
    first = evaluate_position_exit(
        _position(addon_qty=None),
        quote=quote,
        bars=bars,
        state=PositionState(),
        policy=POLICY,
        now=now,
        market="CN",
        latest_expected=latest_expected_closed("CN", now),
    )
    assert first.plan.status == "PENDING"
    assert Decimal(first.plan.position_target) == Decimal("500")
    halved = _position(core_qty="500", addon_qty=None)
    satisfied = evaluate_position_exit(
        halved,
        quote=quote,
        bars=bars,
        state=first.state,
        policy=POLICY,
        now=now + timedelta(minutes=5),
        market="CN",
        latest_expected=latest_expected_closed("CN", now),
    )
    assert satisfied.plan.status == "SATISFIED_BY_SHEET"
    assert any(event["event_type"] == "PLAN_SATISFIED" for event in satisfied.events)
    later = now + timedelta(minutes=10)
    still_weak = weaken_last_adjacent(_bars(until=later))
    again = evaluate_position_exit(
        halved,
        quote=QuoteView(price=Decimal("108"), quote_as_of=later, valid=True),
        bars=still_weak,
        state=satisfied.state,
        policy=POLICY,
        now=later,
        market="CN",
        latest_expected=latest_expected_closed("CN", later),
    )
    assert Decimal(again.position_target) == Decimal("500")
    assert again.plan.status == "SATISFIED_BY_SHEET"
    assert not any(event["event_type"] == "CONFIRMED_WEAK" for event in again.events)


def test_addon_stage_a_failure_does_not_halve_core():
    now = datetime(2026, 9, 16, 14, 0, tzinfo=SH)
    core_entry = datetime(2026, 9, 14, 9, 35, tzinfo=SH)
    addon_entry = datetime(2026, 9, 16, 9, 40, tzinfo=SH)
    bars = weaken_last_adjacent(_bars(until=now, high_close=Decimal("110")))
    quote = QuoteView(price=Decimal("108"), quote_as_of=now, valid=True)
    result = evaluate_position_exit(
        _position(
            core_qty="1000",
            addon_qty="500",
            core_entry=core_entry,
            addon_entry=addon_entry,
            core_price="100",
            addon_price="110",
        ),
        quote=quote,
        bars=bars,
        state=PositionState(),
        policy=POLICY,
        now=now,
        market="CN",
        latest_expected=latest_expected_closed("CN", now),
    )
    by_id = {item.leg_id: item.target_quantity for item in result.leg_exits}
    assert result.plan.status == "PENDING"
    assert result.plan.action == "REDUCE"
    assert by_id["addon"] == Decimal("0")
    assert by_id["core"] == Decimal("1000")
    assert result.position_target == Decimal("1000")


def test_warmup_history_does_not_emit_exit_for_new_healthy_position():
    now = datetime(2026, 9, 16, 10, 30, tzinfo=SH)
    yesterday = datetime(2026, 9, 15, 15, 0, tzinfo=SH)
    bars = weaken_last_adjacent(_bars(until=yesterday), close=Decimal("80"))
    today = session_bars(
        days=[DAY],
        close=Decimal("101"),
        until=now,
        high_close=Decimal("102"),
        high_on=DAY,
    )
    quote = QuoteView(price=Decimal("108"), quote_as_of=now, valid=True)
    result = evaluate_position_exit(
        _position(addon_qty=None, core_entry=datetime(2026, 9, 16, 9, 30, tzinfo=SH)),
        quote=quote,
        bars=bars + today,
        state=PositionState(),
        policy=POLICY,
        now=now,
        market="CN",
        latest_expected=latest_expected_closed("CN", now),
    )
    assert result.plan.status in {"NONE", "SATISFIED_BY_SHEET"}
    assert result.plan.action in {"HOLD", "WATCH"}
    assert result.position_target == Decimal("1000")
    assert not any(event["event_type"] in {"CONFIRMED_WEAK", "SEVERE_BREAK", "HARD_STOP"} for event in result.events)


def test_addon_does_not_inherit_pre_entry_weak_streak():
    now = datetime(2026, 9, 16, 14, 5, tzinfo=SH)
    bars = _bars(until=now)
    weak_at = {datetime(2026, 9, 16, 13, 50, tzinfo=SH), datetime(2026, 9, 16, 13, 55, tzinfo=SH)}
    updated = []
    for bar in bars:
        if bar.bar_end in weak_at:
            updated.append(replace(bar, open=Decimal("110"), high=Decimal("110"), low=Decimal("89"), close=Decimal("90"), amount=Decimal("90") * bar.volume))
        else:
            updated.append(bar)
    quote = QuoteView(price=Decimal("108"), quote_as_of=now, valid=True)
    result = evaluate_position_exit(
        _position(
            core_qty="1000",
            addon_qty="500",
            core_entry=datetime(2026, 9, 14, 9, 35, tzinfo=SH),
            addon_entry=datetime(2026, 9, 16, 14, 0, tzinfo=SH),
            addon_price="110",
        ),
        quote=quote,
        bars=updated,
        state=PositionState(),
        policy=POLICY,
        now=now,
        market="CN",
        latest_expected=latest_expected_closed("CN", now),
    )
    by_id = {item.leg_id: item.target_quantity for item in result.leg_exits}
    assert by_id["addon"] == Decimal("500")
    assert result.position_target >= Decimal("1000")


def test_same_bar_end_does_not_double_count_and_pending_plan_keeps_fixed_target():
    now = datetime(2026, 9, 16, 14, 0, tzinfo=SH)
    bars = weaken_last_adjacent(_bars(until=now, high_close=Decimal("110")))
    quote = QuoteView(price=Decimal("108"), quote_as_of=now, valid=True)
    first = evaluate_position_exit(
        _position(addon_qty=None),
        quote=quote,
        bars=bars,
        state=PositionState(),
        policy=POLICY,
        now=now,
        market="CN",
        latest_expected=latest_expected_closed("CN", now),
    )
    second = evaluate_position_exit(
        _position(addon_qty=None),
        quote=quote,
        bars=bars,
        state=first.state,
        policy=POLICY,
        now=now,
        market="CN",
        latest_expected=latest_expected_closed("CN", now),
    )
    assert second.state.last_bar_end == first.state.last_bar_end
    assert first.plan.status == "PENDING"
    assert Decimal(first.plan.position_target) == Decimal("500")
    assert second.plan.status == "PENDING"
    assert second.plan.position_target == first.plan.position_target
    assert second.plan.revision == first.plan.revision


def test_new_episode_can_exit_after_recovery():
    now = datetime(2026, 9, 16, 14, 0, tzinfo=SH)
    bars = weaken_last_adjacent(_bars(until=now, high_close=Decimal("110")))
    quote = QuoteView(price=Decimal("108"), quote_as_of=now, valid=True)
    first = evaluate_position_exit(
        _position(addon_qty=None),
        quote=quote,
        bars=bars,
        state=PositionState(),
        policy=POLICY,
        now=now,
        market="CN",
        latest_expected=latest_expected_closed("CN", now),
    )
    assert first.plan.status == "PENDING"
    assert Decimal(first.plan.position_target) == Decimal("500")
    halved = _position(core_qty="500", addon_qty=None)
    satisfied = evaluate_position_exit(
        halved,
        quote=quote,
        bars=bars,
        state=first.state,
        policy=POLICY,
        now=now + timedelta(minutes=5),
        market="CN",
        latest_expected=latest_expected_closed("CN", now),
    )
    assert satisfied.plan.status == "SATISFIED_BY_SHEET"
    later = now + timedelta(minutes=10)
    still_weak = weaken_last_adjacent(_bars(until=later, high_close=Decimal("110")))
    again = evaluate_position_exit(
        halved,
        quote=QuoteView(price=Decimal("108"), quote_as_of=later, valid=True),
        bars=still_weak,
        state=satisfied.state,
        policy=POLICY,
        now=later,
        market="CN",
        latest_expected=latest_expected_closed("CN", later),
    )
    assert Decimal(again.position_target) == Decimal("500")
    assert again.plan.status == "SATISFIED_BY_SHEET"
    assert not any(event["event_type"] == "CONFIRMED_WEAK" for event in again.events)
    recovered_at = now + timedelta(minutes=20)
    recovered_bars = recover_last_adjacent(_bars(until=recovered_at, high_close=Decimal("110")))
    recovered = evaluate_position_exit(
        halved,
        quote=QuoteView(price=Decimal("108"), quote_as_of=recovered_at, valid=True),
        bars=recovered_bars,
        state=again.state,
        policy=POLICY,
        now=recovered_at,
        market="CN",
        latest_expected=latest_expected_closed("CN", recovered_at),
    )
    assert recovered.state.episode_consumed is False
    assert any(event["event_type"] == "EPISODE_RECOVERED" for event in recovered.events)
    weak_again_at = now + timedelta(minutes=30)
    new_weak = weaken_last_adjacent(_bars(until=weak_again_at, high_close=Decimal("110")))
    second = evaluate_position_exit(
        halved,
        quote=QuoteView(price=Decimal("108"), quote_as_of=weak_again_at, valid=True),
        bars=new_weak,
        state=recovered.state,
        policy=POLICY,
        now=weak_again_at,
        market="CN",
        latest_expected=latest_expected_closed("CN", weak_again_at),
    )
    assert second.plan.status == "PENDING"
    assert Decimal(second.plan.position_target) == Decimal("250")
    assert any(event["event_type"] == "CONFIRMED_WEAK" for event in second.events)
    assert second.plan.revision == recovered.plan.revision + 1


def test_closed_addon_zero_quantity_satisfies_bound_plan():
    now = datetime(2026, 9, 16, 14, 0, tzinfo=SH)
    plan = ActivePlan(
        revision=1,
        status="PENDING",
        action="REDUCE",
        bound_leg_ids=["core", "addon"],
        leg_targets={"core": "1000", "addon": "0"},
        position_target="1000",
        current_quantity="1500",
        reduce_quantity="500",
    )
    position = PositionInput(
        "a1",
        "p1",
        "600519.SH",
        (
            LegInput("core", "CORE", Decimal("1000"), Decimal("100"), now, status="OPEN"),
            LegInput("addon", "ADDON", Decimal("0"), Decimal("110"), now, status="CLOSED"),
        ),
    )
    result = evaluate_position_exit(
        position,
        quote=QuoteView(price=Decimal("108"), quote_as_of=now, valid=True),
        bars=[],
        state=PositionState(plan=plan, episode_consumed=True),
        policy=POLICY,
        now=now,
        market="CN",
    )
    assert result.plan.status == "SATISFIED_BY_SHEET"
    assert result.needs_review is False
    assert not any(event["event_type"] == "CONFIRMED_WEAK" for event in result.events)
    assert any(event["event_type"] == "PLAN_SATISFIED" for event in result.events)


def test_missing_bound_leg_is_review_not_satisfied():
    now = datetime(2026, 9, 16, 14, 0, tzinfo=SH)
    plan = ActivePlan(
        revision=1,
        status="PENDING",
        action="REDUCE",
        bound_leg_ids=["core", "addon"],
        leg_targets={"core": "1000", "addon": "0"},
        position_target="1000",
    )
    position = PositionInput(
        "a1",
        "p1",
        "600519.SH",
        (LegInput("core", "CORE", Decimal("1000"), Decimal("100"), now, status="OPEN"),),
    )
    result = evaluate_position_exit(
        position,
        quote=QuoteView(price=Decimal("108"), quote_as_of=now, valid=True),
        bars=[],
        state=PositionState(plan=plan, episode_consumed=True),
        policy=POLICY,
        now=now,
        market="CN",
    )
    assert result.plan.status == "PENDING"
    assert result.needs_review is True
    assert any(event["event_type"] == "PLAN_NEEDS_REVIEW" for event in result.events)

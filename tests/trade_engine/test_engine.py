"""Portfolio-risk re-arm and single-candidate position strategies."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from [REDACTED].portfolio.models import ResolvedPosition  # pragma: allowlist secret
from [REDACTED].trade_engine.config import RiskPolicy  # pragma: allowlist secret
from [REDACTED].trade_engine.models import PositionContext, QuoteView  # pragma: allowlist secret
from [REDACTED].trade_engine.strategies import cn_position_intraday_v1 as cn_mod  # pragma: allowlist secret
from [REDACTED].trade_engine.strategies.cn_position_intraday_v1 import CNPositionIntradayV1  # pragma: allowlist secret
from [REDACTED].trade_engine.strategies.portfolio_risk_v1 import PortfolioRiskV1  # pragma: allowlist secret

NOW = datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc)


def _position(*, quantity="1000"):
    return ResolvedPosition(
        source="DB",
        coverage="DB",
        uid=1,
        market="CN",
        account_id="1",
        position_id="11",
        symbol="600519.SH",
        asset_type="STOCK",
        quantity=Decimal(quantity),
        average_cost=Decimal("10"),
    )


def _run(state, *, now=NOW, cash="0", quantity="1000"):
    position = _position(quantity=quantity)
    quotes = {"600519.SH": QuoteView(price=Decimal("100"), quote_as_of=now, valid=True)}
    return PortfolioRiskV1().evaluate_portfolio(
        [position],
        quotes,
        {},
        cash=Decimal(cash),
        market="CN",
        now=now,
        policy=RiskPolicy(max_symbol_weight=Decimal("0.10")),
        strategy_state=state,
    )


def test_portfolio_risk_watch_does_not_set_target():
    signals = _run({})
    assert signals and signals[0].action == "WATCH"
    assert signals[0].suggested_target_quantity is None


def test_portfolio_risk_rearms_after_recovery():
    state = {}
    first = _run(state)
    assert len(first) == 1
    again = _run(state)
    assert again == []
    recovered = _run(state, cash="1000000")
    assert recovered == []
    assert state.get("active_keys") == []
    assert state.get("confirmed_keys") == []
    later = NOW + timedelta(minutes=5)
    restarted = _run(state, now=later)
    assert len(restarted) == 1
    assert restarted[0].action == "WATCH"


def test_portfolio_risk_reject_can_rereview_on_new_bar():
    state = {}
    first = _run(state)
    assert first
    state["last_reviewed_5m_bar"] = first[0].evidence["bar_end"]
    same = _run(state)
    assert same == []
    later = NOW + timedelta(minutes=5)
    again = _run(state, now=later)
    assert len(again) == 1


def test_cn_merges_multiple_rules_into_one_candidate(monkeypatch):
    metrics = {
        "broke_30m_low": True,
        "price_below_vwap": True,
        "high_rvol": True,
        "price_below_ema20": True,
        "change_15m": -2.0,
        "change_5m": -1.0,
        "high_open_fade": True,
        "close": Decimal("10"),
        "vwap": Decimal("11"),
        "ema20": Decimal("12"),
        "rvol": Decimal("2"),
        "bar_end": NOW,
    }
    monkeypatch.setattr(cn_mod, "local_bar_metrics", lambda rows: metrics)
    context = PositionContext(
        market="CN",
        symbol="600519.SH",
        position=_position(),
        quote=QuoteView(Decimal("10"), NOW, True),
        now=NOW,
    )
    signals = CNPositionIntradayV1().evaluate(context)
    assert len(signals) == 1
    assert signals[0].action == "REDUCE"
    assert "跌破前30分钟低点" in signals[0].reason
    assert "短周期走弱" in signals[0].reason
    assert "高开回落" in signals[0].reason
    assert "放量下跌" in signals[0].reason

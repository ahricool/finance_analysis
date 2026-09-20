"""Trade Engine aggregator and portfolio-risk WATCH without sell targets."""

from datetime import datetime, timezone
from decimal import Decimal

from finance_analysis.portfolio.models import ResolvedPosition  # pragma: allowlist secret
from finance_analysis.trade_engine.engine import aggregate_position_signals  # pragma: allowlist secret
from finance_analysis.trade_engine.models import QuoteView, TradeSignalCandidate  # pragma: allowlist secret
from finance_analysis.trade_engine.strategies.portfolio_risk_v1 import PortfolioRiskV1  # pragma: allowlist secret
from finance_analysis.trade_engine.config import RiskPolicy  # pragma: allowlist secret


def _candidate(**changes):
    payload = dict(
        strategy_key="exit_v1",
        strategy_version="1",
        market="CN",
        account_id="1",
        position_id="11",
        symbol="600519.SH",
        action="WATCH",
        suggested_target_quantity=None,
        severity="soft",
        reason="",
        evidence={},
        evaluated_at=datetime(2026, 9, 16, tzinfo=timezone.utc),
        signal_key="k",
    )
    payload.update(changes)
    return TradeSignalCandidate(**payload)


def test_aggregator_takes_more_severe_action_and_min_target():
    result = aggregate_position_signals(
        [
            _candidate(action="WATCH", suggested_target_quantity=Decimal("1000"), signal_key="a"),
            _candidate(action="REDUCE", suggested_target_quantity=Decimal("800"), signal_key="b"),
            _candidate(action="REDUCE", suggested_target_quantity=Decimal("500"), strategy_key="other", signal_key="c"),
        ]
    )
    assert result.action == "REDUCE"
    assert result.suggested_target_quantity == Decimal("500")


def test_portfolio_risk_watch_does_not_set_target():
    now = datetime(2026, 9, 16, tzinfo=timezone.utc)
    position = ResolvedPosition(
        source="DB",
        coverage="DB",
        uid=1,
        market="CN",
        account_id="1",
        position_id="11",
        symbol="600519.SH",
        asset_type="STOCK",
        quantity=Decimal("1000"),
        average_cost=Decimal("10"),
    )
    quotes = {"600519.SH": QuoteView(price=Decimal("100"), quote_as_of=now, valid=True)}
    signals = PortfolioRiskV1().evaluate_portfolio(
        [position],
        quotes,
        {},
        cash=Decimal("0"),
        market="CN",
        now=now,
        policy=RiskPolicy(max_symbol_weight=Decimal("0.10")),
    )
    assert signals and signals[0].action == "WATCH"
    assert signals[0].suggested_target_quantity is None


def test_watch_does_not_change_exit_target():
    result = aggregate_position_signals(
        [
            _candidate(action="EXIT", suggested_target_quantity=Decimal("0"), signal_key="e"),
            _candidate(action="WATCH", suggested_target_quantity=None, strategy_key="portfolio_risk_v1", signal_key="w"),
        ]
    )
    assert result.action == "EXIT"
    assert result.suggested_target_quantity == Decimal("0")

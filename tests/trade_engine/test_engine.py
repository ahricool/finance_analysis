"""Trade Engine aggregator and shared MarketContext."""

from datetime import datetime, timezone
from decimal import Decimal

from finance_analysis.portfolio.models import ResolvedPosition  # pragma: allowlist secret
from finance_analysis.trade_engine.engine import aggregate_position_signals  # pragma: allowlist secret
from finance_analysis.trade_engine.models import MarketContext, QuoteView, TradeSignal  # pragma: allowlist secret
from finance_analysis.trade_engine.strategies.portfolio_risk_v1 import PortfolioRiskV1  # pragma: allowlist secret
from finance_analysis.trade_engine.config import RiskPolicy  # pragma: allowlist secret
from finance_analysis.trade_engine.service import TradeEngineService  # pragma: allowlist secret


def _signal(**changes):
    payload = dict(
        strategy_key="exit_v1",
        strategy_version="1",
        market="CN",
        account_id="1",
        position_id="11",
        symbol="600519.SH",
        action="HOLD",
        suggested_target_quantity=None,
        reason="",
        evidence={},
        evaluated_at=datetime(2026, 9, 16, tzinfo=timezone.utc),
        signal_key="k",
    )
    payload.update(changes)
    return TradeSignal(**payload)


def test_aggregator_takes_more_severe_action_and_min_target():
    result = aggregate_position_signals(
        [
            _signal(action="WATCH", suggested_target_quantity=Decimal("1000"), signal_key="a"),
            _signal(action="REDUCE", suggested_target_quantity=Decimal("800"), signal_key="b"),
            _signal(action="REDUCE", suggested_target_quantity=Decimal("500"), strategy_key="other", signal_key="c"),
        ]
    )
    assert result.action == "REDUCE"
    assert result.suggested_target_quantity == Decimal("500")


def test_portfolio_risk_warning_does_not_set_target():
    now = datetime(2026, 9, 16, tzinfo=timezone.utc)
    context = MarketContext(market="CN", as_of=now, trading_date=now, session_open=True)
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
    signals = PortfolioRiskV1().evaluate(
        [position],
        quotes,
        context,
        {},
        cash=Decimal("0"),
        policy=RiskPolicy(max_symbol_weight=Decimal("0.10")),
    )
    assert signals and signals[0].action == "WARNING"
    assert signals[0].suggested_target_quantity is None


def test_warning_does_not_change_exit_target():
    result = aggregate_position_signals(
        [
            _signal(action="EXIT", suggested_target_quantity=Decimal("0"), signal_key="e"),
            _signal(action="WARNING", suggested_target_quantity=None, strategy_key="portfolio_risk_v1", signal_key="w"),
        ]
    )
    assert result.action == "EXIT"
    assert result.suggested_target_quantity == Decimal("0")


def test_evaluate_market_builds_context_once_and_shares_it():
    now = datetime(2026, 9, 16, tzinfo=timezone.utc)

    class Fake(TradeEngineService):
        def __init__(self):
            self.calls = 0
            self.seen = []

        def _active_uids(self, market):
            return [1, 2]

        def _market_context(self, market, *, now):
            self.calls += 1
            return MarketContext(market=market, as_of=now, trading_date=now, session_open=True)

        def evaluate_uid(self, uid, *, market, now=None, context=None):
            self.seen.append(context)
            return {"positions": [{}, {}], "notified": 0}

    service = Fake()
    result = service.evaluate_market("CN", now=now)
    assert service.calls == 1
    assert result["context_builds"] == 1
    assert result["positions"] == 4
    assert len(service.seen) == 2
    assert service.seen[0] is service.seen[1]

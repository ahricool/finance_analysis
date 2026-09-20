"""Trade Engine service: parallel strategies, LLM resolver, warnings, enabled filter."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from finance_analysis.portfolio.models import ResolvedAccount, ResolvedLot, ResolvedPortfolio, ResolvedPosition  # pragma: allowlist secret
from finance_analysis.trade_engine.models import FinalDecision, QuoteView, StrategyAssessment, StrategyProposal  # pragma: allowlist secret
from finance_analysis.trade_engine.service import TradeEngineService  # pragma: allowlist secret
from finance_analysis.trade_engine.strategies.add_v1 import AddV1  # pragma: allowlist secret
from finance_analysis.trade_engine.strategies.exit_v1 import ExitV1  # pragma: allowlist secret
from finance_analysis.trade_engine.strategies.portfolio_risk_v1 import PortfolioRiskV1  # pragma: allowlist secret

NOW = datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc)
LATER = datetime(2026, 9, 16, 14, 5, tzinfo=timezone.utc)


class NullSources:
    def get_for_uid(self, uid):
        return None

    def list_enabled(self):
        return []


class FakeDB:
    def _run_write_transaction(self, name, write):
        return write(object())


class FakeStates:
    def __init__(self):
        self.signals = []
        self.saved_states = {}
        self.notifications = []

    def get_state(self, session, **kwargs):
        key = (kwargs["account_id"], kwargs["position_id"], kwargs["strategy_key"])
        payload = self.saved_states.get(key)
        if payload is None:
            return None
        return SimpleNamespace(state=payload)

    def has_signal(self, session, *, uid, signal_key):
        return any(item["signal_key"] == signal_key for item in self.signals)

    def add_signal(self, session, **payload):
        self.signals.append(payload)
        return SimpleNamespace(**payload)

    def upsert_state(self, session, **payload):
        key = (payload["account_id"], payload["position_id"], payload["strategy_key"])
        self.saved_states[key] = payload["state"]

    def create_notification(self, session, **payload):
        self.notifications.append(payload)
        return len(self.notifications)


class FakeMarket:
    def __init__(self):
        self.quote_calls = []
        self.daily_calls = []
        self.quotes_map = {}
        self.daily_map = {}

    def quotes(self, symbols, now=None):
        self.quote_calls.append(list(symbols))
        return {symbol: self.quotes_map[symbol] for symbol in symbols if symbol in self.quotes_map}

    def daily_bars(self, symbols, **kwargs):
        self.daily_calls.append(list(symbols))
        return {symbol: self.daily_map.get(symbol, []) for symbol in symbols}


class FakeResolver:
    def __init__(self, portfolio: ResolvedPortfolio):
        self.portfolio = portfolio

    def get_resolved_portfolio(self, uid, *, market=None):
        return self.portfolio


class ScriptedResolver:
    def __init__(self, action="REDUCE", target="700", quantity=None, reason="ok", failed=False):
        self.action = action
        self.target = target
        self.quantity = quantity
        self.reason = reason
        self.failed = failed
        self.calls = []

    def resolve(self, proposals, extras=None):
        self.calls.append(list(proposals))
        if self.failed:
            return FinalDecision(proposals[0].position_id or "", proposals[0].symbol, "NO_ACTION", None, None, "llm_failed", failed=True)
        target = None if self.target is None else Decimal(self.target)
        quantity = None if self.quantity is None else Decimal(self.quantity)
        assessments = tuple(
            StrategyAssessment(item.strategy_key, item.action, "ACCEPT" if item.action == self.action else "REJECT", item.reason)
            for item in proposals
        )
        return FinalDecision(
            proposals[0].position_id or "",
            proposals[0].symbol,
            self.action,  # type: ignore[arg-type]
            quantity,
            target,
            self.reason,
            assessments,
        )


def _proposal(context, *, key, action, quantity=None, target=None, reason="x"):
    qty = None if quantity is None else Decimal(quantity)
    tgt = None if target is None else Decimal(target)
    return StrategyProposal(
        market=context.market,
        account_id=context.position.account_id,
        position_id=context.position.position_id,
        symbol=context.position.symbol,
        strategy_key=key,
        strategy_version="1",
        action=action,
        suggested_quantity=qty,
        suggested_target_quantity=tgt,
        reason=reason,
        evidence={"current_quantity": format(context.position.quantity, "f")},
        evaluated_at=context.now or NOW,
        proposal_key=f"{key}:{context.position.position_id}:{action}:{target or quantity}:{(context.now or NOW).date().isoformat()}",
    )


class HoldExit(ExitV1):
    def evaluate(self, context):
        return []


class ReduceExit(ExitV1):
    def evaluate(self, context):
        return [_proposal(context, key="exit_v1", action="REDUCE", target="700", reason="保护")]


class AddOnly(AddV1):
    def evaluate(self, context):
        return [_proposal(context, key="add_v1", action="ADD", quantity="200", target="1200", reason="买点")]


class Spy:
    def __init__(self, inner):
        self.inner = inner
        self.key = inner.key
        self.version = inner.version
        self.calls = 0
        self.seen_other = []

    def evaluate(self, context):
        self.calls += 1
        self.seen_other.append(list(context.strategy_state.get("other_results") or []))
        return self.inner.evaluate(context)


def _position(symbol="AAPL.US", position_id="11", quantity="1000", *, enabled=True, market="US"):
    return ResolvedPosition(
        source="DB",
        coverage="DB",
        uid=1,
        market=market,
        account_id="1",
        position_id=position_id,
        symbol=symbol,
        asset_type="STOCK",
        quantity=Decimal(quantity),
        average_cost=Decimal("190"),
        lots=(ResolvedLot("core", "CORE", Decimal(quantity), Decimal("190"), NOW),),
        trade_engine_enabled=enabled,
    )


def _portfolio(*positions, cash="1000000", market="US"):
    return ResolvedPortfolio(
        uid=1,
        accounts=(ResolvedAccount("DB", 1, "1", market, market, Decimal(cash), "USD" if market == "US" else "CNY"),),
        positions=positions,
    )


def _service(portfolio, *, resolver=None, strats=None, portfolio_strats=None, market=None):
    service = TradeEngineService(
        resolver=FakeResolver(portfolio),
        market=market or FakeMarket(),
        db=FakeDB(),
        decision_resolver=resolver or ScriptedResolver(),
        position_strategy_loader=lambda m: tuple(strats or (HoldExit(),)),
        portfolio_strategy_loader=lambda m: tuple(portfolio_strats or ()),
    )
    service.sources = NullSources()
    service.states = FakeStates()
    return service


def test_no_proposal_means_zero_llm_zero_signal_zero_notification():
    market = FakeMarket()
    market.quotes_map = {"AAPL.US": QuoteView(Decimal("200"), NOW, True)}
    resolver = ScriptedResolver()
    service = _service(_portfolio(_position()), resolver=resolver, market=market, strats=[HoldExit()])
    result = service.evaluate_uid(1, market="US", now=NOW)
    assert result["proposals"] == 0
    assert result["llm_reviews"] == 0
    assert result["confirmed_signals"] == 0
    assert result["notifications"] == 0
    assert resolver.calls == []
    assert service.states.signals == []
    assert market.quote_calls == [["AAPL.US"]]
    assert market.daily_calls == [["AAPL.US"]]


def test_parallel_strategies_do_not_read_each_other():
    market = FakeMarket()
    market.quotes_map = {"AAPL.US": QuoteView(Decimal("200"), NOW, True)}
    exit_spy = Spy(ReduceExit())
    add_spy = Spy(AddOnly())
    resolver = ScriptedResolver("REDUCE", "700")
    service = _service(_portfolio(_position()), resolver=resolver, market=market, strats=[exit_spy, add_spy])
    service.evaluate_uid(1, market="US", now=NOW)
    assert exit_spy.calls == 1
    assert add_spy.calls == 1
    assert exit_spy.seen_other == [[]]
    assert add_spy.seen_other == [[]]


def test_conflict_proposals_go_to_one_llm_call():
    market = FakeMarket()
    market.quotes_map = {"AAPL.US": QuoteView(Decimal("200"), NOW, True)}
    resolver = ScriptedResolver("REDUCE", "700", reason="综合退出保护")
    service = _service(_portfolio(_position()), resolver=resolver, market=market, strats=[ReduceExit(), AddOnly()])
    result = service.evaluate_uid(1, market="US", now=NOW)
    assert result["llm_reviews"] == 1
    assert len(resolver.calls) == 1
    actions = {item.action for item in resolver.calls[0]}
    assert actions == {"REDUCE", "ADD"}
    row = service.states.signals[0]
    assert row["action"] == "REDUCE"
    assert Decimal(str(row["suggested_target_quantity"])) == Decimal("700")
    body = service.states.notifications[0]["content"]
    assert "exit_v1" in body
    assert "add_v1" in body
    assert "REDUCE" in body
    assert "综合退出保护" in body


def test_no_action_does_not_create_trade_signal_or_trade_notification():
    market = FakeMarket()
    market.quotes_map = {"AAPL.US": QuoteView(Decimal("200"), NOW, True)}
    resolver = ScriptedResolver("NO_ACTION", None, reason="观望")
    service = _service(_portfolio(_position()), resolver=resolver, market=market, strats=[ReduceExit(), AddOnly()])
    result = service.evaluate_uid(1, market="US", now=NOW)
    assert result["resolved_no_action"] == 1
    assert result["confirmed_signals"] == 0
    assert [item for item in service.states.signals if item["action"] != "WARNING"] == []
    assert service.states.notifications == []


def test_portfolio_warning_skips_llm():
    market = FakeMarket()
    market.quotes_map = {"600519.SH": QuoteView(Decimal("100"), NOW, True)}
    resolver = ScriptedResolver()
    position = _position("600519.SH", "21", "10000", market="CN")
    portfolio = _portfolio(position, cash="0", market="CN")
    service = _service(
        portfolio,
        resolver=resolver,
        market=market,
        strats=[HoldExit()],
        portfolio_strats=[PortfolioRiskV1()],
    )
    result = service.evaluate_uid(1, market="CN", now=NOW)
    assert result["llm_reviews"] == 0
    assert result["warnings"] >= 1
    assert result["notifications"] == 1
    assert resolver.calls == []
    assert service.states.notifications[0]["title"] == "A股账户风险"


def test_warning_rearm_uses_new_unique_key():
    market = FakeMarket()
    market.quotes_map = {"600519.SH": QuoteView(Decimal("100"), NOW, True)}
    position = _position("600519.SH", "21", "10000", market="CN")
    service = _service(
        _portfolio(position, cash="0", market="CN"),
        resolver=ScriptedResolver(),
        market=market,
        strats=[HoldExit()],
        portfolio_strats=[PortfolioRiskV1()],
    )
    first = service.evaluate_uid(1, market="CN", now=NOW)
    keys = {item["signal_key"] for item in service.states.signals}
    assert first["warnings"] >= 1
    again = service.evaluate_uid(1, market="CN", now=NOW)
    assert again["warnings"] == 0
    service2 = _service(
        _portfolio(position, cash="10000000", market="CN"),
        resolver=ScriptedResolver(),
        market=market,
        strats=[HoldExit()],
        portfolio_strats=[PortfolioRiskV1()],
    )
    service2.states = service.states
    recovered = service2.evaluate_uid(1, market="CN", now=LATER)
    assert recovered["warnings"] == 0
    service3 = _service(
        _portfolio(position, cash="0", market="CN"),
        resolver=ScriptedResolver(),
        market=market,
        strats=[HoldExit()],
        portfolio_strats=[PortfolioRiskV1()],
    )
    service3.states = service.states
    restarted = service3.evaluate_uid(1, market="CN", now=LATER)
    new_keys = {item["signal_key"] for item in service3.states.signals} - keys
    assert restarted["warnings"] >= 1
    assert new_keys


def test_disabled_position_is_filtered_before_quotes():
    market = FakeMarket()
    market.quotes_map = {
        "AAPL.US": QuoteView(Decimal("200"), NOW, True),
        "NVDA.US": QuoteView(Decimal("100"), NOW, True),
    }
    spy = Spy(HoldExit())
    service = _service(
        _portfolio(_position("AAPL.US", "11", enabled=True), _position("NVDA.US", "12", "50", enabled=False)),
        market=market,
        strats=[spy],
    )
    result = service.evaluate_uid(1, market="US", now=NOW)
    assert market.quote_calls == [["AAPL.US"]]
    assert market.daily_calls == [["AAPL.US"]]
    assert spy.calls == 1
    assert result["positions_analyzed"] == 1


def test_empty_portfolio_skips_market_and_llm():
    market = FakeMarket()
    resolver = ScriptedResolver()
    service = _service(_portfolio(), resolver=resolver, market=market)
    result = service.evaluate_uid(1, market="US", now=NOW)
    assert result["positions_analyzed"] == 0
    assert market.quote_calls == []
    assert market.daily_calls == []
    assert resolver.calls == []


def test_daily_add_proposal_is_resolved_once():
    market = FakeMarket()
    market.quotes_map = {"AAPL.US": QuoteView(Decimal("200"), NOW, True)}
    resolver = ScriptedResolver("ADD", "1200", quantity="200")
    service = _service(_portfolio(_position()), resolver=resolver, market=market, strats=[AddOnly()])
    first = service.evaluate_uid(1, market="US", now=NOW)
    assert first["llm_reviews"] == 1
    second = service.evaluate_uid(1, market="US", now=LATER)
    assert second["llm_reviews"] == 0
    assert len(resolver.calls) == 1

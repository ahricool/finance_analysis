"""Trade Engine service: candidates, LLM review, hard stop, holdings-only universe."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from finance_analysis.portfolio.models import ResolvedAccount, ResolvedLot, ResolvedPortfolio, ResolvedPosition  # pragma: allowlist secret
from finance_analysis.trade_engine.models import QuoteView, ReviewDecision, TradeSignalCandidate  # pragma: allowlist secret
from finance_analysis.trade_engine.service import TradeEngineService  # pragma: allowlist secret
from finance_analysis.trade_engine.strategies.exit_v1 import ExitV1  # pragma: allowlist secret


NOW = datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc)


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
        return 1


class FakeMarket:
    def __init__(self):
        self.quote_calls = []
        self.bar_calls = []
        self.refresh_calls = []
        self.quotes_map = {}
        self.bars_map = {}

    def quotes(self, symbols, now=None):
        self.quote_calls.append(list(symbols))
        return {symbol: self.quotes_map[symbol] for symbol in symbols if symbol in self.quotes_map}

    def cached_five_minute_bars(self, symbols, **kwargs):
        self.bar_calls.append(list(symbols))
        return {symbol: self.bars_map.get(symbol, []) for symbol in symbols}

    def symbols_needing_refresh(self, symbols, now=None):
        return []

    def five_minute_bars(self, symbols, **kwargs):
        self.refresh_calls.append(list(symbols))
        return {}

    def bar_quality(self, symbol, now=None):
        return {}


class FakeResolver:
    def __init__(self, portfolio: ResolvedPortfolio):
        self.portfolio = portfolio

    def get_resolved_portfolio(self, uid, *, market=None):
        return self.portfolio


class ScriptedReviewer:
    def __init__(self, decision="CONFIRM", failed=False):
        self.decision = decision
        self.failed = failed
        self.calls = []

    def review(self, candidates, extras=None):
        self.calls.append(list(candidates))
        return {
            item.signal_key: ReviewDecision(
                self.decision,
                item.action,
                item.suggested_target_quantity,
                "llm",
                failed=self.failed,
            )
            for item in candidates
        }


class HoldExit(ExitV1):
    def evaluate(self, context):
        return []


class ReduceExit(ExitV1):
    def evaluate(self, context):
        stamp = (context.now or NOW).isoformat()
        if context.strategy_state.get("last_processed_5m_bar") == stamp:
            return []
        context.strategy_state["last_processed_5m_bar"] = stamp
        return [
            TradeSignalCandidate(
                market=context.market,
                account_id=context.position.account_id,
                position_id=context.position.position_id,
                symbol=context.position.symbol,
                strategy_key="exit_v1",
                strategy_version="1",
                action="REDUCE",
                suggested_target_quantity=Decimal("500"),
                severity="soft",
                reason="走弱",
                evidence={},
                evaluated_at=context.now or NOW,
                signal_key=f"exit_v1:{context.position.position_id}:soft:{stamp}",
            )
        ]


class HardExit(ExitV1):
    def evaluate(self, context):
        return [
            TradeSignalCandidate(
                market=context.market,
                account_id=context.position.account_id,
                position_id=context.position.position_id,
                symbol=context.position.symbol,
                strategy_key="exit_v1",
                strategy_version="1",
                action="EXIT",
                suggested_target_quantity=Decimal("0"),
                severity="hard",
                reason="hard_stop",
                evidence={"hard": True},
                evaluated_at=NOW,
                signal_key=f"exit_v1:{context.position.position_id}:hard",
            )
        ]


def _position(symbol="AAPL.US", position_id="11", quantity="100"):
    return ResolvedPosition(
        source="DB",
        coverage="DB",
        uid=1,
        market="US",
        account_id="1",
        position_id=position_id,
        symbol=symbol,
        asset_type="STOCK",
        quantity=Decimal(quantity),
        average_cost=Decimal("10"),
        lots=(ResolvedLot("core", "CORE", Decimal(quantity), Decimal("10"), NOW),),
    )


def _portfolio(*positions):
    return ResolvedPortfolio(
        uid=1,
        accounts=(ResolvedAccount("DB", 1, "1", "US", "US", Decimal("1000000"), "USD"),),
        positions=positions,
    )


def _service(portfolio, *, reviewer=None, exit_strategy=None, market=None):
    strategy = exit_strategy or HoldExit()
    service = TradeEngineService(
        resolver=FakeResolver(portfolio),
        market=market or FakeMarket(),
        db=FakeDB(),
        reviewer=reviewer or ScriptedReviewer(),
        position_strategy_loader=lambda market: (strategy,),
        portfolio_strategy_loader=lambda market: (),
    )
    service.sources = NullSources()
    service.states = FakeStates()
    return service


def test_no_signal_means_zero_llm_zero_db_zero_notification():
    market = FakeMarket()
    market.quotes_map = {"AAPL.US": QuoteView(Decimal("12"), NOW, True)}
    reviewer = ScriptedReviewer()
    service = _service(_portfolio(_position()), reviewer=reviewer, market=market, exit_strategy=HoldExit())
    result = service.evaluate_uid(1, market="US", now=NOW)
    assert result["candidates"] == 0
    assert result["llm_reviews"] == 0
    assert result["confirmed_signals"] == 0
    assert result["notifications"] == 0
    assert reviewer.calls == []
    assert service.states.signals == []
    assert service.states.notifications == []
    assert market.quote_calls == [["AAPL.US"]]


def test_soft_confirm_persists_signal_and_notifies():
    market = FakeMarket()
    market.quotes_map = {"AAPL.US": QuoteView(Decimal("12"), NOW, True)}
    reviewer = ScriptedReviewer("CONFIRM")
    service = _service(_portfolio(_position()), reviewer=reviewer, market=market, exit_strategy=ReduceExit())
    result = service.evaluate_uid(1, market="US", now=NOW)
    assert result["candidates"] == 1
    assert result["llm_reviews"] == 1
    assert result["confirmed_signals"] == 1
    assert result["notifications"] == 1
    assert service.states.signals[0]["action"] == "REDUCE"
    assert service.states.notifications
    assert service.states.saved_states[("1", "11", "exit_v1")].get("soft_episode_active") is True


def test_soft_reject_does_not_persist_or_notify():
    market = FakeMarket()
    market.quotes_map = {"AAPL.US": QuoteView(Decimal("12"), NOW, True)}
    reviewer = ScriptedReviewer("REJECT")
    service = _service(_portfolio(_position()), reviewer=reviewer, market=market, exit_strategy=ReduceExit())
    result = service.evaluate_uid(1, market="US", now=NOW)
    assert result["confirmed_signals"] == 0
    assert result["rejected_signals"] == 1
    assert result["notifications"] == 0
    assert service.states.signals == []
    assert service.states.notifications == []


def test_soft_reject_same_bar_does_not_rereview_next_bar_can():
    market = FakeMarket()
    market.quotes_map = {"AAPL.US": QuoteView(Decimal("12"), NOW, True)}
    reviewer = ScriptedReviewer("REJECT")
    service = _service(_portfolio(_position()), reviewer=reviewer, market=market, exit_strategy=ReduceExit())
    first = service.evaluate_uid(1, market="US", now=NOW)
    assert first["llm_reviews"] == 1
    same_bar = service.evaluate_uid(1, market="US", now=NOW)
    assert same_bar["candidates"] == 0
    assert same_bar["llm_reviews"] == 0
    assert len(reviewer.calls) == 1
    later = datetime(2026, 9, 16, 14, 5, tzinfo=timezone.utc)
    again = service.evaluate_uid(1, market="US", now=later)
    assert again["candidates"] == 1
    assert again["llm_reviews"] == 1
    assert again["confirmed_signals"] == 0
    assert len(reviewer.calls) == 2


def test_hard_stop_persists_when_llm_unavailable():
    market = FakeMarket()
    market.quotes_map = {"AAPL.US": QuoteView(Decimal("9"), NOW, True)}
    reviewer = ScriptedReviewer(failed=True)
    service = _service(_portfolio(_position()), reviewer=reviewer, market=market, exit_strategy=HardExit())
    result = service.evaluate_uid(1, market="US", now=NOW)
    assert result["confirmed_signals"] == 1
    assert result["notifications"] == 1
    assert result["llm_reviews"] == 0
    assert service.states.signals[0]["action"] == "EXIT"
    assert service.states.signals[0]["reviewed_by_llm"] is False
    assert reviewer.calls == []


def test_engine_only_requests_held_symbols():
    market = FakeMarket()
    market.quotes_map = {
        "AAPL.US": QuoteView(Decimal("12"), NOW, True),
        "NVDA.US": QuoteView(Decimal("100"), NOW, True),
    }
    service = _service(
        _portfolio(_position("AAPL.US", "11"), _position("NVDA.US", "12", "50")),
        market=market,
        exit_strategy=HoldExit(),
    )
    service.evaluate_uid(1, market="US", now=NOW)
    assert market.quote_calls == [["AAPL.US", "NVDA.US"]]
    assert market.bar_calls == [["AAPL.US", "NVDA.US"]]
    assert market.refresh_calls == []


def test_option_holdings_are_skipped():
    market = FakeMarket()
    market.quotes_map = {"AAPL.US": QuoteView(Decimal("12"), NOW, True)}
    option = ResolvedPosition(
        source="GOOGLE",
        coverage="EXTERNAL_ONLY",
        uid=1,
        market="US",
        account_id="google",
        position_id="opt",
        symbol="AAPL 250117C200",
        asset_type="OPTION",
        quantity=Decimal("1"),
        average_cost=Decimal("2"),
    )
    service = _service(_portfolio(option, _position()), market=market, exit_strategy=HoldExit())
    service.evaluate_uid(1, market="US", now=NOW)
    assert market.quote_calls == [["AAPL.US"]]
    assert market.bar_calls == [["AAPL.US"]]


def test_empty_portfolio_skips_market_and_llm():
    market = FakeMarket()
    reviewer = ScriptedReviewer()
    service = _service(_portfolio(), reviewer=reviewer, market=market, exit_strategy=HoldExit())
    result = service.evaluate_uid(1, market="US", now=NOW)
    assert result["positions_analyzed"] == 0
    assert result["candidates"] == 0
    assert result["llm_reviews"] == 0
    assert result["notifications"] == 0
    assert market.quote_calls == []
    assert market.bar_calls == []
    assert reviewer.calls == []


def test_cn_run_does_not_load_us_strategies():
    seen = []

    def loader(market):
        seen.append(market)
        return (HoldExit(),)

    market = FakeMarket()
    market.quotes_map = {"600519.SH": QuoteView(Decimal("12"), NOW, True)}
    portfolio = ResolvedPortfolio(
        uid=1,
        accounts=(ResolvedAccount("DB", 1, "2", "CN", "CN", Decimal("1000000"), "CNY"),),
        positions=(
            ResolvedPosition(
                source="DB",
                coverage="DB",
                uid=1,
                market="CN",
                account_id="2",
                position_id="21",
                symbol="600519.SH",
                asset_type="STOCK",
                quantity=Decimal("100"),
                average_cost=Decimal("10"),
            ),
        ),
    )
    service = TradeEngineService(
        resolver=FakeResolver(portfolio),
        market=market,
        db=FakeDB(),
        reviewer=ScriptedReviewer(),
        position_strategy_loader=loader,
        portfolio_strategy_loader=lambda market: (),
    )
    service.sources = NullSources()
    service.states = FakeStates()
    service.evaluate_uid(1, market="CN", now=NOW)
    assert seen == ["CN"]
    assert market.quote_calls == [["600519.SH"]]

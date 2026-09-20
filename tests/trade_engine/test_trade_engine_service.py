"""Trade Engine service: one strategy, LLM cannot change action/target, enabled filter."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from [REDACTED].portfolio.models import ResolvedAccount, ResolvedLot, ResolvedPortfolio, ResolvedPosition  # pragma: allowlist secret
from [REDACTED].trade_engine.models import QuoteView, ReviewDecision, TradeSignalCandidate, one_candidate  # pragma: allowlist secret
from [REDACTED].trade_engine.service import TradeEngineService  # pragma: allowlist secret
from [REDACTED].trade_engine.strategies.cn_position_intraday_v1 import CNPositionIntradayV1  # pragma: allowlist secret
from [REDACTED].trade_engine.strategies.exit_v1 import ExitV1  # pragma: allowlist secret


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
    def __init__(self, decision="CONFIRM", failed=False, reason="llm", comment=None):
        self.decision = decision
        self.failed = failed
        self.reason = reason
        self.comment = comment
        self.calls = []

    def review(self, candidates, extras=None):
        self.calls.append(list(candidates))
        return {
            item.signal_key: ReviewDecision(self.decision, self.reason, self.comment, failed=self.failed)
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
                evidence={"bar_end": stamp},
                evaluated_at=context.now or NOW,
                signal_key=f"exit_v1:{context.position.position_id}:soft:{stamp}",
            )
        ]


class AlwaysReduce(ExitV1):
    def evaluate(self, context):
        stamp = (context.now or NOW).isoformat()
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
                evidence={"bar_end": stamp},
                evaluated_at=context.now or NOW,
                signal_key=f"exit_v1:{context.position.position_id}:soft:{stamp}",
            )
        ]


class SoftThenHard(ExitV1):
    def __init__(self):
        self.calls = 0

    def evaluate(self, context):
        self.calls += 1
        if self.calls == 1:
            return [
                TradeSignalCandidate(
                    market=context.market,
                    account_id=context.position.account_id,
                    position_id=context.position.position_id,
                    symbol=context.position.symbol,
                    strategy_key="exit_v1",
                    strategy_version="1",
                    action="REDUCE",
                    suggested_target_quantity=Decimal("1000"),
                    severity="soft",
                    reason="addon soft",
                    evidence={"bar_end": NOW.isoformat()},
                    evaluated_at=NOW,
                    signal_key="exit_v1:11:soft:1000",
                )
            ]
        return [
            TradeSignalCandidate(
                market=context.market,
                account_id=context.position.account_id,
                position_id=context.position.position_id,
                symbol=context.position.symbol,
                strategy_key="exit_v1",
                strategy_version="1",
                action="REDUCE",
                suggested_target_quantity=Decimal("1000"),
                severity="hard",
                reason="hard_stop",
                evidence={"hard": True},
                evaluated_at=LATER,
                signal_key="exit_v1:11:hard:1000",
            )
        ]


class MultiRuleExit(ExitV1):
    def evaluate(self, context):
        common = dict(
            market=context.market,
            account_id=context.position.account_id,
            position_id=context.position.position_id,
            symbol=context.position.symbol,
            strategy_key="exit_v1",
            strategy_version="1",
            suggested_target_quantity=Decimal("500"),
            severity="soft",
            evidence={},
            evaluated_at=context.now or NOW,
        )
        return one_candidate(
            [
                TradeSignalCandidate(action="WATCH", reason="跌破VWAP", signal_key="a", **common),
                TradeSignalCandidate(action="REDUCE", reason="放量", signal_key="b", **common),
                TradeSignalCandidate(action="WATCH", reason="跌破30分钟低点", signal_key="c", **common),
            ]
        )


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


class SpyStrategy:
    def __init__(self, inner):
        self.inner = inner
        self.key = inner.key
        self.version = inner.version
        self.calls = 0

    def evaluate(self, context):
        self.calls += 1
        return self.inner.evaluate(context)


def _position(symbol="AAPL.US", position_id="11", quantity="100", *, enabled=True, strategy_key="exit_v1"):
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
        strategy_key=strategy_key,
        trade_engine_enabled=enabled,
    )


def _portfolio(*positions):
    return ResolvedPortfolio(
        uid=1,
        accounts=(ResolvedAccount("DB", 1, "1", "US", "US", Decimal("1000000"), "USD"),),
        positions=positions,
    )


def _service(portfolio, *, reviewer=None, exit_strategy=None, market=None, loader=None):
    strategy = exit_strategy or HoldExit()
    service = TradeEngineService(
        resolver=FakeResolver(portfolio),
        market=market or FakeMarket(),
        db=FakeDB(),
        reviewer=reviewer or ScriptedReviewer(),
        position_strategy_loader=loader or (lambda market, key=None: strategy),
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
    reviewer = ScriptedReviewer("CONFIRM", comment="最新财报将在两日后公布")
    service = _service(_portfolio(_position()), reviewer=reviewer, market=market, exit_strategy=ReduceExit())
    result = service.evaluate_uid(1, market="US", now=NOW)
    assert result["candidates"] == 1
    assert result["llm_reviews"] == 1
    assert result["confirmed_signals"] == 1
    assert result["notifications"] == 1
    row = service.states.signals[0]
    assert row["action"] == "REDUCE"
    assert Decimal(str(row["suggested_target_quantity"])) == Decimal("500")
    assert row["llm_reason"] == "llm"
    assert row["llm_comment"] == "最新财报将在两日后公布"
    assert "LLM意见 最新财报将在两日后公布" in service.states.notifications[0]["content"]
    assert service.states.saved_states[("1", "11", "exit_v1")].get("soft_episode_active") is True
    assert Decimal(str(service.states.saved_states[("1", "11", "exit_v1")].get("last_confirmed_soft_target"))) == Decimal("500")


def test_llm_confirm_cannot_change_action_or_target():
    market = FakeMarket()
    market.quotes_map = {"AAPL.US": QuoteView(Decimal("12"), NOW, True)}
    reviewer = ScriptedReviewer("CONFIRM", reason="建议全部退出", comment="建议全部退出")
    service = _service(_portfolio(_position()), reviewer=reviewer, market=market, exit_strategy=ReduceExit())
    service.evaluate_uid(1, market="US", now=NOW)
    row = service.states.signals[0]
    assert row["action"] == "REDUCE"
    assert Decimal(str(row["suggested_target_quantity"])) == Decimal("500")


def test_soft_reject_does_not_persist_or_notify_or_confirm_target():
    market = FakeMarket()
    market.quotes_map = {"AAPL.US": QuoteView(Decimal("12"), NOW, True)}
    reviewer = ScriptedReviewer("REJECT")
    service = _service(_portfolio(_position()), reviewer=reviewer, market=market, exit_strategy=ReduceExit())
    result = service.evaluate_uid(1, market="US", now=NOW)
    assert result["confirmed_signals"] == 0
    assert result["rejected_signals"] == 1
    assert result["notifications"] == 0
    assert service.states.signals == []
    state = service.states.saved_states[("1", "11", "exit_v1")]
    assert state.get("last_confirmed_soft_target") is None
    assert state.get("soft_episode_active") in {None, False}


def test_soft_reject_same_bar_does_not_rereview_next_bar_can():
    market = FakeMarket()
    market.quotes_map = {"AAPL.US": QuoteView(Decimal("12"), NOW, True)}
    reviewer = ScriptedReviewer("REJECT")
    service = _service(_portfolio(_position()), reviewer=reviewer, market=market, exit_strategy=AlwaysReduce())
    first = service.evaluate_uid(1, market="US", now=NOW)
    assert first["llm_reviews"] == 1
    same_bar = service.evaluate_uid(1, market="US", now=NOW)
    assert same_bar["llm_reviews"] == 0
    assert len(reviewer.calls) == 1
    again = service.evaluate_uid(1, market="US", now=LATER)
    assert again["candidates"] == 1
    assert again["llm_reviews"] == 1
    assert again["confirmed_signals"] == 0
    assert len(reviewer.calls) == 2


def test_rejected_soft_does_not_block_later_hard_stop():
    market = FakeMarket()
    market.quotes_map = {"AAPL.US": QuoteView(Decimal("12"), NOW, True)}
    reviewer = ScriptedReviewer("REJECT")
    strategy = SoftThenHard()
    service = _service(_portfolio(_position()), reviewer=reviewer, market=market, exit_strategy=strategy)
    first = service.evaluate_uid(1, market="US", now=NOW)
    assert first["confirmed_signals"] == 0
    assert service.states.saved_states[("1", "11", "exit_v1")].get("last_confirmed_soft_target") is None
    second = service.evaluate_uid(1, market="US", now=LATER)
    assert second["confirmed_signals"] == 1
    assert second["notifications"] == 1
    assert second["llm_reviews"] == 0
    assert service.states.signals[0]["action"] == "REDUCE"
    assert Decimal(str(service.states.signals[0]["suggested_target_quantity"])) == Decimal("1000")
    assert service.states.signals[0]["reviewed_by_llm"] is False
    assert service.states.notifications


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


def test_only_active_strategy_is_evaluated():
    market = FakeMarket()
    market.quotes_map = {"AAPL.US": QuoteView(Decimal("12"), NOW, True)}
    exit_spy = SpyStrategy(HoldExit())
    other_spy = SpyStrategy(CNPositionIntradayV1())
    calls = []

    def loader(market, key=None):
        calls.append((market, key))
        return exit_spy if (key or "exit_v1") == "exit_v1" else other_spy

    service = _service(
        _portfolio(_position(strategy_key="exit_v1")),
        market=market,
        loader=loader,
    )
    service.evaluate_uid(1, market="US", now=NOW)
    assert calls == [("US", "exit_v1")]
    assert exit_spy.calls == 1
    assert other_spy.calls == 0


def test_one_position_emits_at_most_one_candidate():
    market = FakeMarket()
    market.quotes_map = {"AAPL.US": QuoteView(Decimal("12"), NOW, True)}
    reviewer = ScriptedReviewer("CONFIRM")
    service = _service(_portfolio(_position()), reviewer=reviewer, market=market, exit_strategy=MultiRuleExit())
    result = service.evaluate_uid(1, market="US", now=NOW)
    assert result["candidates"] == 1
    assert result["llm_reviews"] == 1
    assert len(reviewer.calls[0]) == 1
    assert reviewer.calls[0][0].action == "REDUCE"
    assert "放量" in reviewer.calls[0][0].reason


def test_disabled_position_is_filtered_before_quotes():
    market = FakeMarket()
    market.quotes_map = {
        "AAPL.US": QuoteView(Decimal("12"), NOW, True),
        "NVDA.US": QuoteView(Decimal("100"), NOW, True),
    }
    reviewer = ScriptedReviewer()
    nvda_spy = SpyStrategy(HoldExit())
    aapl_spy = SpyStrategy(HoldExit())

    def loader(market, key=None):
        return aapl_spy

    service = _service(
        _portfolio(_position("AAPL.US", "11", enabled=True), _position("NVDA.US", "12", "50", enabled=False)),
        reviewer=reviewer,
        market=market,
        loader=loader,
        exit_strategy=aapl_spy,
    )
    del nvda_spy
    result = service.evaluate_uid(1, market="US", now=NOW)
    assert market.quote_calls == [["AAPL.US"]]
    assert market.bar_calls == [["AAPL.US"]]
    assert aapl_spy.calls == 1
    assert result["positions_analyzed"] == 1
    assert reviewer.calls == []
    assert service.states.signals == []


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

    def loader(market, key=None):
        seen.append((market, key))
        return HoldExit()

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
    assert seen == [("CN", None)]
    assert market.quote_calls == [["600519.SH"]]

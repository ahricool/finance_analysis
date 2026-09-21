"""Trade Engine service: one market-level LLM, stateless signals, LLM state, notifications."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from finance_analysis.portfolio.models import ResolvedAccount, ResolvedLot, ResolvedPortfolio, ResolvedPosition  # pragma: allowlist secret
from finance_analysis.trade_engine.models import (  # pragma: allowlist secret
    DailyBar,
    MarketDecision,
    PositionTarget,
    QuoteView,
    StrategySignal,
)
from finance_analysis.trade_engine.service import TradeEngineService  # pragma: allowlist secret
from finance_analysis.trade_engine.strategies.add_v1 import AddV1  # pragma: allowlist secret
from finance_analysis.trade_engine.strategies.exit_v1 import ExitV1  # pragma: allowlist secret

NOW = datetime(2026, 9, 16, 14, 0, tzinfo=timezone.utc)


class _Null:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeDB:
    def _run_write_transaction(self, name, write):
        return write(object())

    def get_session(self):
        return _Null()


class FakeStates:
    def __init__(self):
        self.signals = []
        self.llm_state = None
        self.notifications = []

    def get_llm_state(self, session, *, uid, market):
        return self.llm_state

    def upsert_llm_state(self, session, **payload):
        self.llm_state = SimpleNamespace(
            summary=payload["summary"],
            last_decision=payload["last_decision"],
            last_decision_at=payload["decided_at"],
        )
        return self.llm_state

    def has_signal(self, session, *, uid, signal_key):
        return any(item["signal_key"] == signal_key for item in self.signals)

    def add_signal(self, session, **payload):
        self.signals.append(payload)
        return SimpleNamespace(**payload)

    def list_signals(self, session, **payload):
        return []

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
        self.daily_calls.append({"symbols": list(symbols), "start": kwargs.get("start"), "end": kwargs.get("end")})
        return {symbol: self.daily_map.get(symbol, []) for symbol in symbols}


class FakeResolver:
    def __init__(self, portfolio: ResolvedPortfolio):
        self.portfolio = portfolio

    def get_resolved_portfolio(self, uid, *, market=None):
        return self.portfolio


class ScriptedResolver:
    def __init__(self, targets=None, summary="B", reason="ok", failed=False):
        self.targets = targets
        self.summary = summary
        self.reason = reason
        self.failed = failed
        self.calls = []

    def decide(self, context):
        self.calls.append(context)
        if self.failed:
            return MarketDecision(context.market, "llm_failed", (), "", failed=True)
        rows = []
        if self.targets is not None:
            planned = {item["symbol"]: item for item in self.targets}
        else:
            planned = {}
        for item in context.positions:
            symbol = item["symbol"]
            current = Decimal(str(item["quantity"]))
            payload = planned.get(symbol, {"target": format(current, "f"), "reason": "keep"})
            target = Decimal(str(payload["target"]))
            action = "NO_ACTION"
            if target == 0 and current > 0:
                action = "EXIT"
            elif 0 < target < current:
                action = "REDUCE"
            elif target > current:
                action = "ADD"
            rows.append(
                PositionTarget(
                    position_id=str(item["position_id"]),
                    symbol=symbol,
                    current_quantity=current,
                    target_quantity=target,
                    action=action,  # type: ignore[arg-type]
                    reason=payload.get("reason") or self.reason,
                )
            )
        return MarketDecision(context.market, self.reason, tuple(rows), self.summary)


def _signal(context, *, key, action, quantity=None, target=None, reason="x"):
    return StrategySignal(
        strategy_key=key,
        strategy_version="1",
        market=context.market,
        account_id=context.position.account_id,
        position_id=context.position.position_id,
        symbol=context.position.symbol,
        action=action,
        suggested_quantity=None if quantity is None else Decimal(quantity),
        suggested_target_quantity=None if target is None else Decimal(target),
        reason=reason,
        evidence={"current_quantity": format(context.position.quantity, "f")},
        evaluated_at=context.now or NOW,
    )


class HoldExit(ExitV1):
    def evaluate(self, context):
        return []


class ReduceExit(ExitV1):
    def evaluate(self, context):
        return [_signal(context, key="exit_v1", action="REDUCE", target="700", reason="保护")]


class AddOnly(AddV1):
    def evaluate(self, context):
        return [_signal(context, key="add_v1", action="ADD", quantity="200", target="1200", reason="买点")]


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
        opened_at=NOW,
        lots=(ResolvedLot("core", "CORE", Decimal(quantity), Decimal("190"), NOW),),
        trade_engine_enabled=enabled,
    )


def _portfolio(*positions, cash="1000000", market="US"):
    return ResolvedPortfolio(
        uid=1,
        accounts=(ResolvedAccount("DB", 1, "1", market, market, Decimal(cash), "USD" if market == "US" else "CNY"),),
        positions=positions,
    )


def _service(portfolio, *, resolver=None, strats=None, market=None):
    service = TradeEngineService(
        resolver=FakeResolver(portfolio),
        market=market or FakeMarket(),
        db=FakeDB(),
        decision_resolver=resolver or ScriptedResolver(),
        position_strategy_loader=lambda m: tuple(strats or (HoldExit(),)),
        portfolio_strategy_loader=lambda m: (),
    )
    service.states = FakeStates()
    service.portfolio_repo = SimpleNamespace(list_operations_for_symbols=lambda session, **kwargs: [])
    return service


def test_holdings_without_strategy_signals_still_call_llm_once():
    market = FakeMarket()
    market.quotes_map = {
        "AAPL.US": QuoteView(Decimal("200"), NOW, True, today_open=Decimal("198"), today_high=Decimal("201"), today_low=Decimal("197"), today_volume=10, today_turnover=Decimal("2000"), pre_close=Decimal("199"), change_pct=Decimal("0.5")),
        "NVDA.US": QuoteView(Decimal("100"), NOW, True),
        "MSFT.US": QuoteView(Decimal("400"), NOW, True),
    }
    resolver = ScriptedResolver()
    service = _service(
        _portfolio(_position(), _position("NVDA.US", "12", "500"), _position("MSFT.US", "13", "200")),
        resolver=resolver,
        market=market,
        strats=[HoldExit()],
    )
    result = service.evaluate_uid(1, market="US", now=NOW)
    assert result["llm_reviews"] == 1
    assert len(resolver.calls) == 1
    assert [item["symbol"] for item in resolver.calls[0].positions] == ["AAPL.US", "NVDA.US", "MSFT.US"]
    assert resolver.calls[0].portfolio_risk.gross_exposure is not None
    today = resolver.calls[0].positions[0]["today"]
    assert today["open"] == "198"
    assert today["current"] == "200"
    assert today["volume"] == 10
    assert result["confirmed_signals"] == 0
    assert service.states.notifications == []
    assert service.states.llm_state.summary == "B"


def test_empty_market_skips_llm():
    resolver = ScriptedResolver()
    service = _service(_portfolio(), resolver=resolver)
    result = service.evaluate_uid(1, market="US", now=NOW)
    assert result["skipped_llm"] is True
    assert resolver.calls == []


def test_portfolio_risk_facts_enter_llm_without_exit_signal():
    market = FakeMarket()
    market.quotes_map = {"AAPL.US": QuoteView(Decimal("200"), NOW, True)}
    resolver = ScriptedResolver(targets=[{"symbol": "AAPL.US", "target": "700", "reason": "超限"}])
    service = _service(_portfolio(_position(), cash="0"), resolver=resolver, market=market, strats=[HoldExit()])
    # Override cash via portfolio already 1_000_000; force high exposure via quantity.
    result = service.evaluate_uid(1, market="US", now=NOW)
    risk = resolver.calls[0].portfolio_risk
    assert risk.max_gross_exposure == Decimal("0.50")
    assert result["confirmed_signals"] == 1
    assert service.states.signals[0]["action"] == "REDUCE"
    assert "0.50" in service.states.notifications[0]["content"] or "50" in service.states.notifications[0]["content"]


def test_one_reduce_signal_and_no_action_position():
    market = FakeMarket()
    market.quotes_map = {
        "AAPL.US": QuoteView(Decimal("200"), NOW, True),
        "NVDA.US": QuoteView(Decimal("100"), NOW, True),
    }
    resolver = ScriptedResolver(
        targets=[
            {"symbol": "AAPL.US", "target": "700", "reason": "保护"},
            {"symbol": "NVDA.US", "target": "500", "reason": "保持"},
        ]
    )
    service = _service(
        _portfolio(_position(), _position("NVDA.US", "12", "500")),
        resolver=resolver,
        market=market,
        strats=[ReduceExit()],
    )
    result = service.evaluate_uid(1, market="US", now=NOW)
    assert result["confirmed_signals"] == 1
    assert service.states.signals[0]["symbol"] == "AAPL.US"
    assert service.states.signals[0]["action"] == "REDUCE"
    body = service.states.notifications[0]["content"]
    assert "exit_v1" in body
    assert "REDUCE" in body
    assert "700" in body


def test_disabled_position_skips_strategy_but_stays_in_context():
    market = FakeMarket()
    market.quotes_map = {
        "AAPL.US": QuoteView(Decimal("200"), NOW, True),
        "NVDA.US": QuoteView(Decimal("100"), NOW, True),
    }
    exit_strategy = ReduceExit()
    resolver = ScriptedResolver()
    service = _service(
        _portfolio(_position(enabled=False), _position("NVDA.US", "12", "500")),
        resolver=resolver,
        market=market,
        strats=[exit_strategy],
    )
    service.evaluate_uid(1, market="US", now=NOW)
    context = resolver.calls[0]
    by_symbol = {item["symbol"]: item for item in context.positions}
    assert by_symbol["AAPL.US"]["trade_engine_enabled"] is False
    assert by_symbol["NVDA.US"]["trade_engine_enabled"] is True
    assert all(item.symbol != "AAPL.US" for item in context.strategy_signals)


def test_trade_history_enters_llm():
    market = FakeMarket()
    market.quotes_map = {"AAPL.US": QuoteView(Decimal("200"), NOW, True)}
    resolver = ScriptedResolver()
    service = _service(_portfolio(_position()), resolver=resolver, market=market)
    service.portfolio_repo = SimpleNamespace(
        list_operations_for_symbols=lambda session, **kwargs: [
            SimpleNamespace(
                position_id="11",
                side="BUY",
                quantity=Decimal("1000"),
                price=Decimal("190"),
                executed_at=NOW,
                note="open core",
            )
        ]
    )
    service.evaluate_uid(1, market="US", now=NOW)
    history = resolver.calls[0].positions[0]["trade_history"]
    assert history[0]["side"] == "BUY"
    assert history[0]["quantity"] == "1000"
    assert history[0]["price"] == "190"
    assert history[0]["note"] == "open core"


def test_llm_state_round_trip():
    market = FakeMarket()
    market.quotes_map = {"AAPL.US": QuoteView(Decimal("200"), NOW, True)}
    first = ScriptedResolver(summary="A")
    service = _service(_portfolio(_position()), resolver=first, market=market)
    service.evaluate_uid(1, market="US", now=NOW)
    assert service.states.llm_state.summary == "A"
    second = ScriptedResolver(summary="B")
    service.decision_resolver = second
    service.evaluate_uid(1, market="US", now=NOW)
    assert second.calls[0].previous.summary == "A"
    assert service.states.llm_state.summary == "B"


def test_llm_daily_bars_are_last_15_completed_only():
    market = FakeMarket()
    market.quotes_map = {"AAPL.US": QuoteView(Decimal("200"), NOW, True)}
    rows = []
    day = date(2026, 8, 1)
    for index in range(20):
        rows.append(DailyBar(day, Decimal("10"), Decimal("11"), Decimal("9"), Decimal("10"), 100))
        day = date.fromordinal(day.toordinal() + 1)
    market.daily_map = {"AAPL.US": rows}
    resolver = ScriptedResolver()
    service = _service(_portfolio(_position()), resolver=resolver, market=market)
    service.evaluate_uid(1, market="US", now=NOW)
    bars = resolver.calls[0].positions[0]["daily_bars_15"]
    assert len(bars) == 15
    assert bars[0]["date"] == rows[-15].trade_date.isoformat()
    assert bars[-1]["date"] == rows[-1].trade_date.isoformat()


def test_strategy_error_does_not_block_other_strategy_or_llm():
    class Boom(ExitV1):
        def evaluate(self, context):
            raise RuntimeError("boom")

    market = FakeMarket()
    market.quotes_map = {"AAPL.US": QuoteView(Decimal("200"), NOW, True)}
    resolver = ScriptedResolver(targets=[{"symbol": "AAPL.US", "target": "700", "reason": "risk"}])
    service = _service(_portfolio(_position()), resolver=resolver, market=market, strats=[Boom(), AddOnly()])
    result = service.evaluate_uid(1, market="US", now=NOW)
    assert result["strategy_error_count"] == 1
    assert result["llm_reviews"] == 1
    assert any(item.strategy_key == "add_v1" for item in resolver.calls[0].strategy_signals)

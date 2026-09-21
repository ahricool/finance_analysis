# -*- coding: utf-8 -*-
"""Run Trade Engine: stateless strategies, one market-level LLM decision."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from decimal import Decimal
from typing import Any, Sequence

from sqlalchemy.orm import Session

from ..core.time import utc_now  # pragma: allowlist secret
from ..database.repositories.portfolio import PortfolioRepository  # pragma: allowlist secret
from ..database.repositories.trade_engine import TradeEngineRepository  # pragma: allowlist secret
from ..database.session import DatabaseManager  # pragma: allowlist secret
from ..notification.service import NotificationService  # pragma: allowlist secret
from ..portfolio.resolver import PortfolioResolver  # pragma: allowlist secret
from .config import get_risk_policy  # pragma: allowlist secret
from .daily import bar_indicators, history_start_date, llm_daily_bars  # pragma: allowlist secret
from .market import RiskMarketGateway  # pragma: allowlist secret
from .models import (  # pragma: allowlist secret
    LLM_SUMMARY_MAX,
    TRADE_HISTORY_LIMIT,
    DailyBar,
    MarketDecision,
    MarketTradeDecisionContext,
    PositionContext,
    PositionTarget,
    PreviousLLMState,
    QuoteView,
    StrategySignal,
    TRADE_ACTIONS,
    TradeHistoryItem,
    TradeSignal,
)
from .notify import push_after_commit, render_trade_message  # pragma: allowlist secret
from .position_risk import compute_position_risk  # pragma: allowlist secret
from .registry import portfolio_strategies, position_strategies, strategies_for  # pragma: allowlist secret
from .resolver import MarketDecisionResolver, serialize_signal, web_search_supported  # pragma: allowlist secret
from .strategies.portfolio_risk_v1 import compute_portfolio_risk_facts  # pragma: allowlist secret
from .valuation import build_market_portfolio_context  # pragma: allowlist secret

logger = logging.getLogger(__name__)


def _empty_stats(market: str, **extra: Any) -> dict[str, Any]:
    payload = {
        "status": "OK",
        "market": market,
        "positions_analyzed": 0,
        "valuation_positions": 0,
        "candidates": 0,
        "proposals": 0,
        "llm_reviews": 0,
        "confirmed_signals": 0,
        "rejected_signals": 0,
        "resolved_no_action": 0,
        "notifications": 0,
        "strategy_errors": [],
        "strategy_error_count": 0,
        "valuation_complete": True,
        "elapsed_ms": 0,
        "skipped_llm": False,
    }
    payload.update(extra)
    return payload


def _run_strategy(strategy, context: PositionContext) -> dict[str, Any]:
    try:
        produced = [item for item in strategy.evaluate(context) if item.action in TRADE_ACTIONS]
        return {"key": strategy.key, "version": strategy.version, "signals": produced, "error_type": None}
    except Exception as exc:
        logger.exception("trade_engine strategy failed strategy=%s symbol=%s", strategy.key, context.symbol)
        return {"key": strategy.key, "version": strategy.version, "signals": [], "error_type": type(exc).__name__}


def _dump(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _today_ohlcv(quote: QuoteView | None) -> dict[str, Any]:
    if quote is None:
        return {
            "open": None,
            "high": None,
            "low": None,
            "current": None,
            "volume": None,
            "turnover": None,
            "pre_close": None,
            "change_pct": None,
            "quote_time": None,
        }
    return {
        "open": _dump(quote.today_open),
        "high": _dump(quote.today_high),
        "low": _dump(quote.today_low),
        "current": _dump(quote.price),
        "volume": quote.today_volume,
        "turnover": _dump(quote.today_turnover),
        "pre_close": _dump(quote.pre_close),
        "change_pct": _dump(quote.change_pct),
        "quote_time": None if quote.quote_as_of is None else quote.quote_as_of.isoformat(),
    }


class TradeEngineService:
    def __init__(
        self,
        *,
        resolver: PortfolioResolver | None = None,
        market: RiskMarketGateway | None = None,
        db: DatabaseManager | None = None,
        notifier: NotificationService | None = None,
        reviewer=None,
        decision_resolver: MarketDecisionResolver | None = None,
        position_strategy_loader=None,
        portfolio_strategy_loader=None,
    ) -> None:
        self.db = db or DatabaseManager.get_instance()
        self.resolver = resolver or PortfolioResolver()
        self.market = market or RiskMarketGateway()
        self.states = TradeEngineRepository(self.db)
        self.portfolio_repo = PortfolioRepository(self.db)
        self.notifier = notifier
        self.decision_resolver = decision_resolver or reviewer or MarketDecisionResolver()
        self._position_strategy_loader = position_strategy_loader or position_strategies
        self._portfolio_strategy_loader = portfolio_strategy_loader or portfolio_strategies

    def list_strategies(self, market: str) -> list[dict[str, str]]:
        return [
            {
                "key": item.key,
                "version": item.version,
                "role": "portfolio" if item.key == "portfolio_risk_v1" else "position",
            }
            for item in strategies_for(market)
        ]

    def evaluate_market(self, market: str, *, now: datetime | None = None, uid: int | None = None) -> dict[str, Any]:
        current = now or utc_now()
        uids = [uid] if uid is not None else self._active_uids(market)
        totals = _empty_stats(market)
        users = 0
        error_rows: list[dict[str, str]] = []
        for user in uids:
            result = self.evaluate_uid(user, market=market, now=current)
            users += 1
            for key in (
                "positions_analyzed",
                "valuation_positions",
                "candidates",
                "proposals",
                "llm_reviews",
                "confirmed_signals",
                "rejected_signals",
                "resolved_no_action",
                "notifications",
                "strategy_error_count",
            ):
                totals[key] += int(result.get(key) or 0)
            error_rows.extend(result.get("strategy_errors") or [])
            if result.get("valuation_complete") is False:
                totals["valuation_complete"] = False
        totals["users"] = users
        totals["evaluated"] = users
        totals["strategy_errors"] = error_rows
        return totals

    def evaluate_uid(self, uid: int, *, market: str, now: datetime | None = None) -> dict[str, Any]:
        current = now or utc_now()
        portfolio = self.resolver.get_resolved_portfolio(uid, market=market)
        valuation_positions = list(portfolio.valuation_positions(market))
        if not valuation_positions:
            return _empty_stats(market, uid=uid, skipped_llm=True)
        symbols = list(dict.fromkeys(item.symbol for item in valuation_positions))
        quotes = self.market.quotes(symbols, now=current)
        policy = get_risk_policy()
        start = history_start_date(valuation_positions, now=current, lookback_days=policy.daily_lookback_days)
        daily = self.market.daily_bars(symbols, start=start, end=current.date(), now=current)
        book = build_market_portfolio_context(portfolio, market=market, quotes=quotes, daily=daily)
        if not book.valuation_complete:
            logger.warning(
                "trade_engine valuation incomplete market=%s uid=%s missing=%s",
                market,
                uid,
                ",".join(book.incomplete_symbols),
            )
        operations = self._trade_history(uid, symbols)

        def write(session: Session):
            contexts: dict[str, PositionContext] = {}
            signals: list[StrategySignal] = []
            risk_map = {}
            strategy_errors: list[dict[str, str]] = []
            strats = list(self._position_strategy_loader(market))
            for position in book.positions:
                bars = daily.get(position.symbol, [])
                quote = quotes.get(position.symbol)
                risk = compute_position_risk(position, bars, policy)
                risk_map[position.position_id] = risk
                position_value = book.market_values.get(position.position_id, Decimal("0"))
                history = operations.get(position.position_id, ())
                ctx = PositionContext(
                    market=position.market,
                    symbol=position.symbol,
                    position=position,
                    quote=quote,
                    daily_bars=tuple(bars),
                    risk=risk,
                    now=current,
                    policy=policy,
                    cash=book.cash,
                    market_nav=book.nav or Decimal("0"),
                    position_value=position_value,
                    valuation_source=book.valuation_sources.get(position.position_id),
                    valuation_complete=book.valuation_complete,
                    trade_history=history,
                )
                contexts[position.position_id] = ctx
                if not position.trade_engine_eligible:
                    continue
                pending_jobs = [(strategy, ctx) for strategy in strats]
                produced_here: list[StrategySignal] = []
                if pending_jobs:
                    workers = max(1, min(len(pending_jobs), 4))
                    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="te-strat") as pool:
                        futures = [pool.submit(_run_strategy, strategy, job_ctx) for strategy, job_ctx in pending_jobs]
                        for future in as_completed(futures):
                            payload = future.result()
                            if payload["error_type"]:
                                strategy_errors.append(
                                    {
                                        "symbol": position.symbol,
                                        "strategy": payload["key"],
                                        "error_type": payload["error_type"],
                                    }
                                )
                                continue
                            produced_here.extend(payload["signals"])
                signals.extend(sorted(produced_here, key=lambda item: item.strategy_key))

            facts = compute_portfolio_risk_facts(book, risk_map, policy=policy)
            llm_row = self.states.get_llm_state(session, uid=uid, market=market)
            previous = PreviousLLMState(
                summary="" if llm_row is None else (llm_row.summary or ""),
                last_decision={} if llm_row is None or not isinstance(llm_row.last_decision, dict) else llm_row.last_decision,
                last_decision_at=None if llm_row is None else llm_row.last_decision_at,
            )
            client = getattr(self.decision_resolver, "_client_or_none", lambda: None)()
            search_ok = web_search_supported(client)
            decision_context = MarketTradeDecisionContext(
                market=market,
                cash=book.cash,
                nav=book.nav,
                gross_exposure=facts.gross_exposure,
                policy={
                    "max_symbol_weight": format(policy.max_symbol_weight, "f"),
                    "risk_per_symbol": format(policy.risk_per_symbol, "f"),
                    "total_open_risk": format(policy.total_open_risk, "f"),
                    "max_gross_exposure": format(policy.max_gross_exposure, "f"),
                },
                positions=tuple(
                    self._llm_position(
                        contexts[position.position_id],
                        book,
                        daily.get(position.symbol, []),
                        quotes.get(position.symbol),
                    )
                    for position in book.positions
                ),
                strategy_signals=tuple(signals),
                portfolio_risk=facts,
                previous=previous,
                recent_signals=tuple(self._recent_official_signals(session, uid=uid, market=market)),
                web_search_available=search_ok,
                evaluated_at=current,
            )
            decision = self.decision_resolver.decide(decision_context)
            llm_reviews = 0 if decision.failed else 1
            created: list[TradeSignal] = []
            if not decision.failed:
                last_decision = {
                    "market": market,
                    "portfolio_reason": decision.portfolio_reason,
                    "positions": [
                        {
                            "symbol": item.symbol,
                            "current_quantity": format(item.current_quantity, "f"),
                            "target_quantity": format(item.target_quantity, "f"),
                            "action": item.action,
                            "reason": item.reason,
                        }
                        for item in decision.positions
                    ],
                    "state_summary": decision.state_summary,
                }
                self.states.upsert_llm_state(
                    session,
                    uid=uid,
                    market=market,
                    summary=decision.state_summary[:LLM_SUMMARY_MAX],
                    last_decision=last_decision,
                    decided_at=current,
                )
                for item in decision.positions:
                    if item.action not in TRADE_ACTIONS or item.target_quantity == item.current_quantity:
                        continue
                    signal = self._to_signal(item, contexts.get(item.position_id), signals, facts, decision, current)
                    if self.states.has_signal(session, uid=uid, signal_key=signal.signal_key):
                        continue
                    created.append(signal)

            pushes: list[tuple[int, str, str]] = []
            if created:
                title, body = render_trade_message(
                    market=market,
                    signals=created,
                    strategy_signals=signals,
                    portfolio_risk=facts,
                )
                notification_id = self.states.create_notification(session, uid=uid, title=title, content=body)
                pushes.append((notification_id, title, body))
                for signal in created:
                    self.states.add_signal(
                        session,
                        uid=uid,
                        market=signal.market,
                        account_id=signal.account_id,
                        position_id=signal.position_id,
                        symbol=signal.symbol,
                        strategy_key=signal.strategy_key,
                        strategy_version=signal.strategy_version,
                        action=signal.action,
                        suggested_quantity=signal.suggested_quantity,
                        suggested_target_quantity=signal.suggested_target_quantity,
                        reason=signal.reason,
                        llm_reason=signal.llm_reason,
                        reviewed_by_llm=signal.reviewed_by_llm,
                        evidence=signal.evidence,
                        signal_key=signal.signal_key,
                        evaluated_at=signal.evaluated_at,
                        notification_id=notification_id,
                    )
            no_action = 0 if decision.failed else sum(1 for item in decision.positions if item.action == "NO_ACTION")
            return {
                **_empty_stats(market),
                "uid": uid,
                "positions_analyzed": len(book.strategy_positions),
                "valuation_positions": len(book.positions),
                "candidates": len(signals),
                "proposals": len(signals),
                "llm_reviews": llm_reviews,
                "confirmed_signals": len(created),
                "resolved_no_action": no_action,
                "notifications": len(pushes),
                "strategy_errors": strategy_errors,
                "strategy_error_count": len(strategy_errors),
                "valuation_complete": book.valuation_complete,
                "valuation_source": {
                    position.position_id: book.valuation_sources.get(position.position_id)
                    for position in book.positions
                },
                "nav": None if book.nav is None else format(book.nav, "f"),
                "cash": format(book.cash, "f"),
                "pushes": pushes,
                "symbols": symbols,
                "web_search_available": search_ok,
            }

        result = self.db._run_write_transaction("trade_engine.evaluate_uid", write)
        for notification_id, title, body in result.pop("pushes", []) or []:
            push_after_commit(notification_id=notification_id, title=title, content=body, service=self.notifier)
        return result

    def list_position_views(self, uid: int, *, market: str | None = None) -> list[dict[str, Any]]:
        portfolio = self.resolver.get_resolved_portfolio(uid, market=market)
        positions = list(portfolio.positions if market is None else portfolio.positions_for_market(market))
        symbols = list(dict.fromkeys(item.symbol for item in positions))
        now = utc_now()
        quotes = self.market.quotes(symbols, now=now) if symbols else {}
        policy = get_risk_policy()
        start = history_start_date(positions, now=now, lookback_days=policy.daily_lookback_days) if positions else now.date()
        daily = self.market.daily_bars(symbols, start=start, end=now.date(), now=now) if symbols else {}
        with self.db.get_session() as session:
            signal_rows = self.states.list_signals(session, uid=uid, market=market, limit=200)
        latest: dict[str, Any] = {}
        for row in signal_rows:
            if row.position_id and row.position_id not in latest:
                latest[row.position_id] = row
        views = []
        for position in positions:
            risk = compute_position_risk(position, daily.get(position.symbol, ()), policy)
            signal = latest.get(position.position_id)
            views.append(
                {
                    "account_id": position.account_id,
                    "position_id": position.position_id,
                    "symbol": position.symbol,
                    "source": position.source,
                    "coverage": position.coverage,
                    "quantity": format(position.quantity, "f"),
                    "average_cost": format(position.average_cost, "f"),
                    "strategies": [item.key for item in position_strategies(position.market)],
                    "trade_engine_enabled": bool(position.trade_engine_enabled),
                    "action": None if signal is None else signal.action,
                    "suggested_quantity": None
                    if signal is None or getattr(signal, "suggested_quantity", None) is None
                    else format(signal.suggested_quantity, "f"),
                    "suggested_target_quantity": None
                    if signal is None or signal.suggested_target_quantity is None
                    else format(signal.suggested_target_quantity, "f"),
                    "reason": None if signal is None else signal.reason,
                    "llm_reason": None if signal is None else getattr(signal, "llm_reason", None),
                    "profit_stage": risk.profit_stage,
                    "active_stop": None if risk.active_stop is None else format(risk.active_stop, "f"),
                    "highest_confirmed_close": None
                    if risk.high_watermark is None
                    else format(risk.high_watermark, "f"),
                    "quote_valid": bool(quotes.get(position.symbol) and quotes[position.symbol].valid),
                }
            )
        return views

    def list_signals(self, uid: int, *, market: str | None = None, position_id: str | None = None, limit: int = 100):
        with self.db.get_session() as session:
            rows = self.states.list_signals(session, uid=uid, market=market, position_id=position_id, limit=limit)
            return [
                {
                    "id": row.id,
                    "market": row.market,
                    "account_id": row.account_id,
                    "position_id": row.position_id,
                    "symbol": row.symbol,
                    "strategy_key": row.strategy_key,
                    "strategy_version": row.strategy_version,
                    "action": row.action,
                    "suggested_quantity": None
                    if getattr(row, "suggested_quantity", None) is None
                    else format(row.suggested_quantity, "f"),
                    "suggested_target_quantity": None
                    if row.suggested_target_quantity is None
                    else format(row.suggested_target_quantity, "f"),
                    "reason": row.reason,
                    "llm_reason": row.llm_reason,
                    "reviewed_by_llm": bool(row.reviewed_by_llm),
                    "evidence": row.evidence or {},
                    "signal_key": row.signal_key,
                    "evaluated_at": row.evaluated_at,
                    "notification_id": row.notification_id,
                    "created_at": row.created_at,
                }
                for row in rows
            ]

    def _active_uids(self, market: str) -> list[int]:
        with self.db.get_session() as session:
            return sorted(set(self.portfolio_repo.list_uids_with_open_positions(session, market=market)))

    def _trade_history(self, uid: int, symbols: Sequence[str]) -> dict[str, tuple[TradeHistoryItem, ...]]:
        with self.db.get_session() as session:
            rows = self.portfolio_repo.list_operations_for_symbols(session, uid=uid, symbols=symbols)
        grouped: dict[str, list[TradeHistoryItem]] = {}
        for row in rows:
            grouped.setdefault(str(row.position_id), []).append(
                TradeHistoryItem(
                    side=row.side,
                    quantity=row.quantity,
                    price=row.price,
                    executed_at=row.executed_at,
                    note=row.note,
                )
            )
        return {key: tuple(value) for key, value in grouped.items()}

    def _recent_official_signals(self, session: Session, *, uid: int, market: str) -> list[dict[str, Any]]:
        rows = self.states.list_signals(session, uid=uid, market=market, limit=8)
        payload = []
        for row in reversed(rows):
            payload.append(
                {
                    "symbol": row.symbol,
                    "action": row.action,
                    "target_quantity": None
                    if row.suggested_target_quantity is None
                    else format(row.suggested_target_quantity, "f"),
                    "reason": row.llm_reason or row.reason,
                    "evaluated_at": None if row.evaluated_at is None else row.evaluated_at.isoformat(),
                }
            )
        return payload

    def _llm_position(self, context: PositionContext, book, bars: Sequence[DailyBar], quote: QuoteView | None) -> dict[str, Any]:
        position = context.position
        price = book.valuation_prices.get(position.position_id)
        value = book.market_values.get(position.position_id)
        weight = None if book.nav in (None, Decimal("0")) or value is None else value / book.nav
        pnl = None if price is None else (price - position.average_cost) * position.quantity
        lots = []
        if position.trade_engine_enabled:
            entry_times = {item.lot_id: item.entry_time for item in position.lots}
            for lot in context.risk.lots:
                entry_time = entry_times.get(lot.lot_id)
                lots.append(
                    {
                        "lot_id": lot.lot_id,
                        "role": lot.role,
                        "entry_price": format(lot.entry_price, "f"),
                        "entry_time": None if entry_time is None else entry_time.isoformat(),
                        "remaining_quantity": format(lot.quantity, "f"),
                        "high_watermark": _dump(lot.high_watermark),
                        "profit_stage": lot.profit_stage,
                        "active_stop": _dump(lot.active_stop),
                        "structure_stop": _dump(lot.structure_stop),
                        "open_risk": None
                        if price is None or lot.active_stop is None
                        else format(lot.quantity * max(price - lot.active_stop, Decimal("0")), "f"),
                    }
                )
        history = context.trade_history
        if position.opened_at is not None:
            history = tuple(item for item in history if item.executed_at >= position.opened_at)
        history = history[-TRADE_HISTORY_LIMIT:]
        indicators = {key: _dump(value) for key, value in bar_indicators(bars).items()}
        return {
            "symbol": position.symbol,
            "name": position.name,
            "position_id": position.position_id,
            "quantity": format(position.quantity, "f"),
            "average_cost": format(position.average_cost, "f"),
            "current_price": _dump(price),
            "market_value": _dump(value),
            "position_weight": _dump(weight),
            "unrealized_pnl": _dump(pnl),
            "trade_engine_enabled": bool(position.trade_engine_enabled),
            "lots": lots,
            "trade_history": [
                {
                    "side": item.side,
                    "quantity": format(item.quantity, "f"),
                    "price": format(item.price, "f"),
                    "executed_at": item.executed_at.isoformat(),
                    "note": item.note,
                }
                for item in history
            ],
            "daily_bars_15": [
                {
                    "date": bar.trade_date.isoformat(),
                    "open": format(bar.open, "f"),
                    "high": format(bar.high, "f"),
                    "low": format(bar.low, "f"),
                    "close": format(bar.close, "f"),
                    "volume": bar.volume,
                }
                for bar in llm_daily_bars(bars)
            ],
            "indicators": indicators,
            "today": _today_ohlcv(quote),
        }

    @staticmethod
    def _to_signal(
        target: PositionTarget,
        context: PositionContext | None,
        signals: Sequence[StrategySignal],
        facts,
        decision: MarketDecision,
        now: datetime,
    ) -> TradeSignal:
        quantity = abs(target.target_quantity - target.current_quantity)
        stamp = now.strftime("%Y%m%d%H%M")
        signal_key = f"final:{target.symbol}:{target.action}:{format(target.target_quantity, 'f')}:{stamp}"
        if len(signal_key) > 190:
            signal_key = signal_key[:190]
        related = [item for item in signals if item.symbol == target.symbol]
        position = None if context is None else context.position
        return TradeSignal(
            strategy_key="market_llm",
            strategy_version="1",
            market=None if context is None else context.market,
            account_id=None if position is None else position.account_id,
            position_id=target.position_id,
            symbol=target.symbol,
            action=target.action,  # type: ignore[arg-type]
            suggested_quantity=quantity,
            suggested_target_quantity=target.target_quantity,
            reason=target.reason or decision.portfolio_reason,
            llm_reason=target.reason or decision.portfolio_reason,
            evidence={
                "current_quantity": format(target.current_quantity, "f"),
                "target_quantity": format(target.target_quantity, "f"),
                "portfolio_reason": decision.portfolio_reason,
                "strategy_signals": [serialize_signal(item) for item in related],
                "portfolio_risk": {
                    "gross_exposure": _dump(facts.gross_exposure),
                    "max_gross_exposure": _dump(facts.max_gross_exposure),
                    "position": None
                    if target.symbol not in facts.positions
                    else {
                        "weight": _dump(facts.positions[target.symbol].weight),
                        "max_weight": _dump(facts.positions[target.symbol].max_weight),
                        "open_risk": _dump(facts.positions[target.symbol].open_risk),
                        "risk_limit": _dump(facts.positions[target.symbol].risk_limit),
                    },
                },
            },
            evaluated_at=now,
            signal_key=signal_key,
            reviewed_by_llm=True,
        )

# -*- coding: utf-8 -*-
"""Run Trade Engine on current holdings only: candidates → LLM review → signals."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from ..core.time import utc_now  # pragma: allowlist secret
from ..database.repositories.holdings import HoldingsRepository  # pragma: allowlist secret
from ..database.repositories.portfolio import PortfolioRepository, _dec  # pragma: allowlist secret
from ..database.repositories.trade_engine import TradeEngineRepository  # pragma: allowlist secret
from ..database.session import DatabaseManager  # pragma: allowlist secret
from ..notification.service import NotificationService  # pragma: allowlist secret
from ..portfolio.resolver import PortfolioResolver  # pragma: allowlist secret
from .config import get_risk_policy  # pragma: allowlist secret
from .indicators import annotate  # pragma: allowlist secret
from .market import RiskMarketGateway  # pragma: allowlist secret
from .models import PositionContext, TradeSignal, TradeSignalCandidate  # pragma: allowlist secret
from .notify import push_after_commit, render_trade_message  # pragma: allowlist secret
from .registry import portfolio_strategies, position_strategies, strategies_for  # pragma: allowlist secret
from .reviewer import TradeSignalReviewer, clamp_review  # pragma: allowlist secret


def _empty_stats(market: str, **extra: Any) -> dict[str, Any]:
    payload = {
        "status": "OK",
        "market": market,
        "positions_analyzed": 0,
        "candidates": 0,
        "llm_reviews": 0,
        "confirmed_signals": 0,
        "rejected_signals": 0,
        "notifications": 0,
        "elapsed_ms": 0,
    }
    payload.update(extra)
    return payload


class TradeEngineService:
    def __init__(
        self,
        *,
        resolver: PortfolioResolver | None = None,
        market: RiskMarketGateway | None = None,
        db: DatabaseManager | None = None,
        notifier: NotificationService | None = None,
        reviewer: TradeSignalReviewer | None = None,
        position_strategy_loader=None,
        portfolio_strategy_loader=None,
    ) -> None:
        self.db = db or DatabaseManager.get_instance()
        self.resolver = resolver or PortfolioResolver()
        self.market = market or RiskMarketGateway()
        self.states = TradeEngineRepository(self.db)
        self.portfolio_repo = PortfolioRepository(self.db)
        self.sources = HoldingsRepository(self.db)
        self.notifier = notifier
        self.reviewer = reviewer or TradeSignalReviewer()
        self._position_strategy_loader = position_strategy_loader or position_strategies
        self._portfolio_strategy_loader = portfolio_strategy_loader or portfolio_strategies

    def list_strategies(self, market: str) -> list[dict[str, str]]:
        return [{"key": item.key, "version": item.version} for item in strategies_for(market)]

    def evaluate_market(self, market: str, *, now: datetime | None = None, uid: int | None = None) -> dict[str, Any]:
        current = now or utc_now()
        uids = [uid] if uid is not None else self._active_uids(market)
        totals = _empty_stats(market)
        users = 0
        for user in uids:
            result = self.evaluate_uid(user, market=market, now=current)
            users += 1
            for key in ("positions_analyzed", "candidates", "llm_reviews", "confirmed_signals", "rejected_signals", "notifications"):
                totals[key] += int(result.get(key) or 0)
        totals["users"] = users
        totals["evaluated"] = users
        return totals

    def evaluate_uid(self, uid: int, *, market: str, now: datetime | None = None) -> dict[str, Any]:
        current = now or utc_now()
        portfolio = self.resolver.get_resolved_portfolio(uid, market=market)
        eligible = list(portfolio.stock_positions(market))
        if not eligible:
            return _empty_stats(market, uid=uid)
        symbols = [item.symbol for item in eligible]
        quotes = self.market.quotes(symbols, now=current)
        start = current - timedelta(days=20)
        bars = self.market.cached_five_minute_bars(symbols, start=start, end=current, now=current)
        needed = self.market.symbols_needing_refresh(symbols, now=current)
        if needed:
            bars.update(
                self.market.five_minute_bars(
                    needed,
                    start=start,
                    end=current,
                    now=current,
                    refresh=True,
                    timeout_seconds=get_risk_policy().five_minute_timeout_seconds,
                )
            )
        policy = get_risk_policy()
        source = self.sources.get_for_uid(uid)
        if source is not None:
            policy = policy.merge(source.risk_policy)

        def write(session: Session):
            candidates: list[TradeSignalCandidate] = []
            next_states: dict[tuple[str, str, str], dict[str, Any]] = {}
            exit_states: dict[str, dict[str, Any]] = {}
            contexts: dict[str, PositionContext] = {}
            position_strats = list(self._position_strategy_loader(market))
            portfolio_strats = list(self._portfolio_strategy_loader(market))
            for position in eligible:
                quality = self.market.bar_quality(position.symbol, now=current)
                symbol_bars = bars.get(position.symbol, [])
                indicators = annotate(list(symbol_bars), policy=policy, market=position.market, now=current)
                for strategy in position_strats:
                    row = self.states.get_state(
                        session,
                        uid=uid,
                        account_id=position.account_id,
                        position_id=position.position_id,
                        strategy_key=strategy.key,
                    )
                    state = deepcopy(row.state) if row is not None and isinstance(row.state, dict) else {}
                    context = PositionContext(
                        market=position.market,
                        symbol=position.symbol,
                        position=position,
                        quote=quotes.get(position.symbol),
                        five_minute_bars=symbol_bars,
                        technical_indicators=indicators,
                        strategy_state=state,
                        now=current,
                        bars_stale=bool(quality.get("stale")),
                        latest_expected=quality.get("latest_expected_closed"),
                        policy=policy,
                    )
                    contexts[position.position_id] = context
                    produced = strategy.evaluate(context)
                    next_states[(position.account_id, position.position_id, strategy.key)] = state
                    if strategy.key == "exit_v1":
                        exit_states[position.position_id] = state
                    candidates.extend(produced)
            cash = sum((_dec(item.cash) for item in portfolio.accounts if item.market == market), start=Decimal("0"))
            portfolio_state: dict[str, Any] = {}
            for strategy in portfolio_strats:
                row = self.states.get_state(
                    session,
                    uid=uid,
                    account_id="portfolio",
                    position_id="portfolio",
                    strategy_key=strategy.key,
                )
                portfolio_state = deepcopy(row.state) if row is not None and isinstance(row.state, dict) else {}
                produced = strategy.evaluate_portfolio(
                    eligible,
                    quotes,
                    exit_states,
                    cash=cash,
                    market=market,
                    now=current,
                    policy=policy,
                    strategy_state=portfolio_state,
                )
                candidates.extend(produced)
                next_states[("portfolio", "portfolio", strategy.key)] = portfolio_state

            hard = [item for item in candidates if item.hard]
            soft = [item for item in candidates if not item.hard]
            llm_reviews = 0
            rejected = 0
            confirmed: list[TradeSignal] = []

            for item in hard:
                # Hard stop is deterministic final. LLM is not required and cannot reject.
                confirmed.append(self._to_signal(item, llm_reason=None, reviewed=False))

            if soft:
                extras_map = {item.signal_key: self._extras(item, contexts.get(item.position_id or "")) for item in soft}
                decisions = self.reviewer.review(soft, extras=extras_map)
                llm_reviews += len(soft)
                for item in soft:
                    raw = decisions.get(item.signal_key)
                    if raw is None or raw.failed:
                        rejected += 1
                        continue
                    current_qty = Decimal("0")
                    context = contexts.get(item.position_id or "")
                    if context is not None:
                        current_qty = context.position.quantity
                    clamped = clamp_review(item, raw, current_quantity=current_qty)
                    if clamped.decision != "CONFIRM":
                        rejected += 1
                        continue
                    confirmed.append(self._to_signal(item, clamped=clamped, reviewed=True))
                    if item.strategy_key == "exit_v1" and item.action in {"REDUCE", "EXIT"}:
                        key = (item.account_id or "", item.position_id or "", "exit_v1")
                        if key in next_states:
                            next_states[key]["soft_episode_active"] = True
                            next_states[key]["last_soft_signal_key"] = item.signal_key

            created: list[TradeSignal] = []
            for signal in confirmed:
                if self.states.has_signal(session, uid=uid, signal_key=signal.signal_key):
                    continue
                created.append(signal)
            notification_id = None
            title_body = None
            if created:
                title_body = render_trade_message(market=market, signals=created, contexts=contexts, quotes=quotes)
                title, body = title_body
                notification_id = self.states.create_notification(session, uid=uid, title=title, content=body)
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
                    suggested_target_quantity=signal.suggested_target_quantity,
                    reason=signal.deterministic_reason,
                    llm_reason=signal.llm_reason,
                    reviewed_by_llm=signal.reviewed_by_llm,
                    evidence=signal.evidence,
                    signal_key=signal.signal_key,
                    evaluated_at=signal.evaluated_at,
                    notification_id=notification_id,
                )
            for (account_id, position_id, strategy_key), state in next_states.items():
                version = next(
                    (item.version for item in position_strats + portfolio_strats if item.key == strategy_key),
                    "1",
                )
                self.states.upsert_state(
                    session,
                    uid=uid,
                    account_id=account_id,
                    position_id=position_id,
                    strategy_key=strategy_key,
                    strategy_version=version,
                    state=state,
                    evaluated_at=current,
                )
            return {
                **_empty_stats(market),
                "uid": uid,
                "positions_analyzed": len(eligible),
                "candidates": len(candidates),
                "llm_reviews": llm_reviews,
                "confirmed_signals": len(created),
                "rejected_signals": rejected,
                "notifications": 1 if created else 0,
                "notification_id": notification_id,
                "title_body": title_body,
                "symbols": symbols,
            }

        result = self.db._run_write_transaction("trade_engine.evaluate_uid", write)
        if result.get("notification_id") and result.get("title_body"):
            title, body = result["title_body"]
            push_after_commit(
                notification_id=result["notification_id"],
                title=title,
                content=body,
                service=self.notifier,
            )
        result.pop("title_body", None)
        return result

    def list_position_views(self, uid: int, *, market: str | None = None) -> list[dict[str, Any]]:
        portfolio = self.resolver.get_resolved_portfolio(uid, market=market)
        with self.db.get_session() as session:
            signals = self.states.list_signals(session, uid=uid, market=market, limit=200)
            states = self.states.list_states(session, uid=uid)
        latest: dict[str, Any] = {}
        for row in signals:
            if row.position_id and row.position_id not in latest:
                latest[row.position_id] = row
        state_map = {(row.account_id, row.position_id, row.strategy_key): row for row in states}
        views = []
        for position in portfolio.positions:
            if market and position.market != market:
                continue
            exit_state = state_map.get((position.account_id, position.position_id, "exit_v1"))
            payload = exit_state.state if exit_state is not None else {}
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
                    "action": None if signal is None else signal.action,
                    "suggested_target_quantity": None
                    if signal is None or signal.suggested_target_quantity is None
                    else format(signal.suggested_target_quantity, "f"),
                    "reason": None if signal is None else signal.reason,
                    "llm_reason": None if signal is None else getattr(signal, "llm_reason", None),
                    "profit_stage": payload.get("profit_stage"),
                    "active_stop": payload.get("active_stop"),
                    "highest_confirmed_close": payload.get("highest_confirmed_close"),
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
            uids = set(self.portfolio_repo.list_uids_with_open_positions(session, market=market))
        for source in self.sources.list_enabled():
            uids.add(source.uid)
        return sorted(uids)

    @staticmethod
    def _extras(candidate: TradeSignalCandidate, context: PositionContext | None) -> dict[str, Any]:
        extras: dict[str, Any] = {"reason": candidate.reason, "evidence": candidate.evidence}
        if context is None:
            return extras
        quote = context.quote
        position = context.position
        bars = list(context.five_minute_bars)[-6:]
        extras.update(
            {
                "quantity": format(position.quantity, "f"),
                "average_cost": format(position.average_cost, "f"),
                "current_price": None if quote is None else format(quote.price, "f"),
                "lots": [{"role": lot.role, "qty": format(lot.quantity, "f")} for lot in position.lots],
                "active_stop": context.strategy_state.get("active_stop"),
                "profit_stage": context.strategy_state.get("profit_stage"),
                "recent_5m": [
                    {"end": bar.bar_end.isoformat(), "c": format(bar.close, "f"), "v": bar.volume}
                    for bar in bars
                ],
            }
        )
        return extras

    @staticmethod
    def _to_signal(candidate: TradeSignalCandidate, *, clamped=None, llm_reason: str | None = None, reviewed: bool = False) -> TradeSignal:
        action = candidate.action if clamped is None else clamped.action
        target = candidate.suggested_target_quantity if clamped is None else clamped.target_quantity
        llm_text = llm_reason if clamped is None else clamped.reason
        return TradeSignal(
            strategy_key=candidate.strategy_key,
            strategy_version=candidate.strategy_version,
            market=candidate.market,
            account_id=candidate.account_id,
            position_id=candidate.position_id,
            symbol=candidate.symbol,
            action=action,
            suggested_target_quantity=target,
            reason=candidate.reason,
            deterministic_reason=candidate.reason,
            llm_reason=llm_text,
            reviewed_by_llm=reviewed,
            evidence=candidate.evidence,
            evaluated_at=candidate.evaluated_at,
            signal_key=candidate.signal_key,
        )

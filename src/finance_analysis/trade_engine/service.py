# -*- coding: utf-8 -*-
"""Run Trade Engine: parallel position strategies, one LLM resolver, independent warnings."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from ..core.time import utc_now  # pragma: allowlist secret
from ..database.repositories.holdings import HoldingsRepository  # pragma: allowlist secret
from ..database.repositories.portfolio import PortfolioRepository  # pragma: allowlist secret
from ..database.repositories.trade_engine import TradeEngineRepository  # pragma: allowlist secret
from ..database.session import DatabaseManager  # pragma: allowlist secret
from ..notification.service import NotificationService  # pragma: allowlist secret
from ..portfolio.resolver import PortfolioResolver  # pragma: allowlist secret
from .config import get_risk_policy  # pragma: allowlist secret
from .market import RiskMarketGateway  # pragma: allowlist secret
from .models import FinalDecision, PositionContext, StrategyProposal, TradeSignal, TRADE_ACTIONS  # pragma: allowlist secret
from .notify import push_after_commit, render_trade_message, render_warning_message  # pragma: allowlist secret
from .position_risk import compute_position_risk  # pragma: allowlist secret
from .registry import portfolio_strategies, position_strategies, strategies_for  # pragma: allowlist secret
from .resolver import TradeDecisionResolver, serialize_proposal  # pragma: allowlist secret
from .strategies.exit_v1 import EXIT_REVIEW_COOLDOWN  # pragma: allowlist secret
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
        "warnings": 0,
        "notifications": 0,
        "strategy_errors": [],
        "strategy_error_count": 0,
        "valuation_complete": True,
        "elapsed_ms": 0,
    }
    payload.update(extra)
    return payload


def _parse_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _run_strategy(strategy, context: PositionContext) -> dict[str, Any]:
    try:
        produced = [item for item in strategy.evaluate(context) if item.action in TRADE_ACTIONS]
        return {
            "key": strategy.key,
            "version": strategy.version,
            "proposals": produced,
            "state": context.strategy_state,
            "error_type": None,
        }
    except Exception as exc:
        logger.exception("trade_engine strategy failed strategy=%s symbol=%s", strategy.key, context.symbol)
        return {
            "key": strategy.key,
            "version": strategy.version,
            "proposals": [],
            "state": context.strategy_state,
            "error_type": type(exc).__name__,
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
        decision_resolver: TradeDecisionResolver | None = None,
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
        self.decision_resolver = decision_resolver or reviewer or TradeDecisionResolver()
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
                "warnings",
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
            return _empty_stats(market, uid=uid)
        symbols = list(dict.fromkeys(item.symbol for item in valuation_positions))
        quotes = self.market.quotes(symbols, now=current)
        policy = get_risk_policy()
        source = self.sources.get_for_uid(uid)
        if source is not None:
            policy = policy.merge(source.risk_policy)
        start = (current - timedelta(days=policy.daily_lookback_days)).date()
        daily = self.market.daily_bars(symbols, start=start, end=current.date(), now=current)
        book = build_market_portfolio_context(portfolio, market=market, quotes=quotes, daily=daily)
        if not book.valuation_complete:
            logger.warning(
                "trade_engine valuation incomplete market=%s uid=%s missing=%s",
                market,
                uid,
                ",".join(book.incomplete_symbols),
            )

        def write(session: Session):
            next_states: dict[tuple[str, str, str], dict[str, Any]] = {}
            used_versions: dict[str, str] = {}
            contexts: dict[str, PositionContext] = {}
            proposals: list[StrategyProposal] = []
            risk_map = {}
            strategy_errors: list[dict[str, str]] = []
            strats = list(self._position_strategy_loader(market))
            portfolio_strats = list(self._portfolio_strategy_loader(market))
            for item in list(strats) + list(portfolio_strats):
                used_versions[item.key] = item.version
            for position in book.positions:
                exit_row = self.states.get_state(
                    session,
                    uid=uid,
                    account_id=position.account_id,
                    position_id=position.position_id,
                    strategy_key="exit_v1",
                )
                exit_state = deepcopy(exit_row.state) if exit_row is not None and isinstance(exit_row.state, dict) else {}
                bars = daily.get(position.symbol, [])
                quote = quotes.get(position.symbol)
                risk, _lots = compute_position_risk(position, bars, exit_state, policy)
                risk_map[position.position_id] = risk
                if not position.trade_engine_eligible:
                    continue
                position_value = book.market_values.get(position.position_id, Decimal("0"))
                pending_jobs = []
                for strategy in strats:
                    row = self.states.get_state(
                        session,
                        uid=uid,
                        account_id=position.account_id,
                        position_id=position.position_id,
                        strategy_key=strategy.key,
                    )
                    state = deepcopy(row.state) if row is not None and isinstance(row.state, dict) else {}
                    ctx = PositionContext(
                        market=position.market,
                        symbol=position.symbol,
                        position=position,
                        quote=quote,
                        daily_bars=tuple(bars),
                        strategy_state=state,
                        risk=risk,
                        now=current,
                        policy=policy,
                        cash=book.cash,
                        market_nav=book.nav or Decimal("0"),
                        position_value=position_value,
                        valuation_source=book.valuation_sources.get(position.position_id),
                        valuation_complete=book.valuation_complete,
                    )
                    pending_jobs.append((strategy, ctx))
                produced_here: list[StrategyProposal] = []
                workers = max(1, min(len(pending_jobs), 4))
                if pending_jobs:
                    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="te-strat") as pool:
                        futures = [pool.submit(_run_strategy, strategy, ctx) for strategy, ctx in pending_jobs]
                        for future in as_completed(futures):
                            payload = future.result()
                            key = payload["key"]
                            used_versions[key] = payload["version"]
                            if payload["error_type"]:
                                strategy_errors.append(
                                    {
                                        "symbol": position.symbol,
                                        "strategy": key,
                                        "error_type": payload["error_type"],
                                    }
                                )
                                continue
                            next_states[(position.account_id, position.position_id, key)] = payload["state"]
                            produced_here.extend(payload["proposals"])
                contexts[position.position_id] = pending_jobs[0][1] if pending_jobs else PositionContext(
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
                )
                proposals.extend(sorted(produced_here, key=lambda item: item.strategy_key))

            warnings = []
            for strategy in portfolio_strats:
                row = self.states.get_state(
                    session,
                    uid=uid,
                    account_id="portfolio",
                    position_id="portfolio",
                    strategy_key=strategy.key,
                )
                portfolio_state = deepcopy(row.state) if row is not None and isinstance(row.state, dict) else {}
                warnings.extend(
                    strategy.evaluate_portfolio(
                        book,
                        risk_map,
                        now=current,
                        policy=policy,
                        strategy_state=portfolio_state,
                    )
                )
                next_states[("portfolio", "portfolio", strategy.key)] = portfolio_state

            trade_proposals = [item for item in proposals if item.action in TRADE_ACTIONS]
            unresolved: list[StrategyProposal] = []
            for item in trade_proposals:
                state = next_states.setdefault(
                    (item.account_id or "", item.position_id or "", item.strategy_key), {}
                )
                resolved = set(state.get("resolved_proposal_keys") or [])
                if item.proposal_key in resolved:
                    continue
                if self._exit_cooling(item, state, current):
                    continue
                if self.states.has_signal(session, uid=uid, signal_key=item.proposal_key):
                    resolved.add(item.proposal_key)
                    state["resolved_proposal_keys"] = sorted(resolved)
                    continue
                unresolved.append(item)

            llm_reviews = 0
            resolved_no_action = 0
            created: list[TradeSignal] = []
            grouped: dict[str, list[StrategyProposal]] = {}
            for item in unresolved:
                grouped.setdefault(item.position_id or "", []).append(item)
            for position_id, group in grouped.items():
                extras = self._extras(group, contexts.get(position_id))
                decision = self.decision_resolver.resolve(group, extras=extras)
                llm_reviews += 1
                if decision.failed:
                    resolved_no_action += 1
                    continue
                for item in group:
                    state = next_states.setdefault(
                        (item.account_id or "", item.position_id or "", item.strategy_key), {}
                    )
                    self._remember_review(item, state, current, decision.action)
                if decision.action == "NO_ACTION":
                    resolved_no_action += 1
                    continue
                signal = self._to_signal(group, decision)
                if self.states.has_signal(session, uid=uid, signal_key=signal.signal_key):
                    continue
                created.append(signal)

            warning_created = [item for item in warnings if not self.states.has_signal(session, uid=uid, signal_key=item.warning_key)]
            pushes: list[tuple[int, str, str]] = []
            if created:
                title, body = render_trade_message(market=market, signals=created, contexts=contexts, quotes=quotes)
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
            if warning_created:
                title, body = render_warning_message(market=market, warnings=warning_created)
                notification_id = self.states.create_notification(session, uid=uid, title=title, content=body)
                pushes.append((notification_id, title, body))
                for warning in warning_created:
                    self.states.add_signal(
                        session,
                        uid=uid,
                        market=warning.market,
                        account_id=warning.account_id,
                        position_id=warning.position_id,
                        symbol=warning.symbol,
                        strategy_key="portfolio_risk_v1",
                        strategy_version="1",
                        action="WARNING",
                        suggested_quantity=None,
                        suggested_target_quantity=None,
                        reason=warning.reason,
                        llm_reason=None,
                        reviewed_by_llm=False,
                        evidence=warning.evidence,
                        signal_key=warning.warning_key,
                        evaluated_at=warning.evaluated_at,
                        notification_id=notification_id,
                    )
            for (account_id, position_id, strategy_key), state in next_states.items():
                self.states.upsert_state(
                    session,
                    uid=uid,
                    account_id=account_id,
                    position_id=position_id,
                    strategy_key=strategy_key,
                    strategy_version=used_versions.get(strategy_key, "1"),
                    state=state,
                    evaluated_at=current,
                )
            return {
                **_empty_stats(market),
                "uid": uid,
                "positions_analyzed": len(book.strategy_positions),
                "valuation_positions": len(book.positions),
                "candidates": len(trade_proposals),
                "proposals": len(trade_proposals),
                "llm_reviews": llm_reviews,
                "confirmed_signals": len(created),
                "resolved_no_action": resolved_no_action,
                "warnings": len(warning_created),
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
            }

        result = self.db._run_write_transaction("trade_engine.evaluate_uid", write)
        for notification_id, title, body in result.pop("pushes", []) or []:
            push_after_commit(notification_id=notification_id, title=title, content=body, service=self.notifier)
        return result

    def list_position_views(self, uid: int, *, market: str | None = None) -> list[dict[str, Any]]:
        portfolio = self.resolver.get_resolved_portfolio(uid, market=market)
        with self.db.get_session() as session:
            signals = self.states.list_signals(session, uid=uid, market=market, limit=200)
            states = self.states.list_states(session, uid=uid)
        latest: dict[str, Any] = {}
        for row in signals:
            if row.action == "WARNING":
                continue
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
                if row.action != "WARNING"
            ]

    def _active_uids(self, market: str) -> list[int]:
        with self.db.get_session() as session:
            uids = set(self.portfolio_repo.list_uids_with_open_positions(session, market=market))
        for source in self.sources.list_enabled():
            uids.add(source.uid)
        return sorted(uids)

    @staticmethod
    def _exit_cooling(item: StrategyProposal, state: dict[str, Any], now: datetime) -> bool:
        if item.strategy_key != "exit_v1":
            return False
        if state.get("exit_review_key") != item.proposal_key:
            return False
        reviewed = _parse_dt(state.get("exit_review_at"))
        return reviewed is not None and now - reviewed < EXIT_REVIEW_COOLDOWN

    @staticmethod
    def _remember_review(item: StrategyProposal, state: dict[str, Any], now: datetime, action: str) -> None:
        if item.strategy_key == "exit_v1" and action == "NO_ACTION":
            state["exit_review_at"] = now.isoformat()
            state["exit_review_key"] = item.proposal_key
            return
        keys = set(state.get("resolved_proposal_keys") or [])
        keys.add(item.proposal_key)
        state["resolved_proposal_keys"] = sorted(keys)

    @staticmethod
    def _extras(proposals: list[StrategyProposal], context: PositionContext | None) -> dict[str, Any]:
        extras: dict[str, Any] = {"proposals": [serialize_proposal(item) for item in proposals]}
        if context is None:
            return extras
        quote = context.quote
        position = context.position
        extras.update(
            {
                "quantity": format(position.quantity, "f"),
                "average_cost": format(position.average_cost, "f"),
                "current_price": None if quote is None else format(quote.price, "f"),
                "lots": [{"role": lot.role, "qty": format(lot.quantity, "f")} for lot in position.lots],
                "active_stop": None if context.risk.active_stop is None else format(context.risk.active_stop, "f"),
                "profit_stage": context.risk.profit_stage,
                "had_addon": position.had_addon,
                "cash": format(context.cash, "f"),
                "market_nav": format(context.market_nav, "f"),
                "valuation_complete": context.valuation_complete,
                "valuation_source": context.valuation_source,
            }
        )
        return extras

    @staticmethod
    def _to_signal(proposals: list[StrategyProposal], decision: FinalDecision) -> TradeSignal:
        first = proposals[0]
        fingerprint = "+".join(sorted(item.proposal_key for item in proposals))
        target = decision.target_quantity
        quantity = decision.quantity
        signal_key = f"final:{first.position_id}:{decision.action}:{format(target or quantity or 0, 'f')}:{fingerprint}"
        if len(signal_key) > 190:
            signal_key = signal_key[:190]
        return TradeSignal(
            strategy_key="llm_resolver",
            strategy_version="1",
            market=first.market,
            account_id=first.account_id,
            position_id=first.position_id,
            symbol=first.symbol,
            action=decision.action,  # type: ignore[arg-type]
            suggested_quantity=quantity,
            suggested_target_quantity=target,
            reason=decision.reason,
            llm_reason=decision.reason,
            evidence={
                "proposals": [serialize_proposal(item) for item in proposals],
                "assessments": [
                    {
                        "strategy": item.strategy,
                        "action": item.action,
                        "decision": item.decision,
                        "reason": item.reason,
                    }
                    for item in decision.assessments
                ],
            },
            evaluated_at=first.evaluated_at,
            signal_key=signal_key,
            reviewed_by_llm=True,
        )

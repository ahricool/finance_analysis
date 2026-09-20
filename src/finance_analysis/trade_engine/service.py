# -*- coding: utf-8 -*-
"""Run Trade Engine: resolve holdings, one MarketContext, strategies, persist, notify."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from finance_analysis.core.time import utc_now  # pragma: allowlist secret
from finance_analysis.database.repositories.holdings import HoldingsRepository  # pragma: allowlist secret
from finance_analysis.database.repositories.portfolio import PortfolioRepository, _dec  # pragma: allowlist secret
from finance_analysis.database.repositories.trade_engine import TradeEngineRepository  # pragma: allowlist secret
from finance_analysis.database.session import DatabaseManager  # pragma: allowlist secret
from finance_analysis.notification.service import NotificationService  # pragma: allowlist secret
from finance_analysis.portfolio.resolver import PortfolioResolver  # pragma: allowlist secret
from finance_analysis.trade_engine.config import get_risk_policy  # pragma: allowlist secret
from finance_analysis.trade_engine.engine import aggregate_position_signals, should_persist  # pragma: allowlist secret
from finance_analysis.trade_engine.market import RiskMarketGateway  # pragma: allowlist secret
from finance_analysis.trade_engine.market_context import build_cn_market_context, build_us_market_context  # pragma: allowlist secret
from finance_analysis.trade_engine.models import MarketContext, TradeSignal  # pragma: allowlist secret
from finance_analysis.trade_engine.notify import push_after_commit, render_trade_message  # pragma: allowlist secret
from finance_analysis.trade_engine.registry import position_strategies, portfolio_strategies, strategies_for  # pragma: allowlist secret


class TradeEngineService:
    def __init__(
        self,
        *,
        resolver: PortfolioResolver | None = None,
        market: RiskMarketGateway | None = None,
        db: DatabaseManager | None = None,
        notifier: NotificationService | None = None,
        context_builder=None,
    ) -> None:
        self.db = db or DatabaseManager.get_instance()
        self.resolver = resolver or PortfolioResolver()
        self.market = market or RiskMarketGateway()
        self.states = TradeEngineRepository(self.db)
        self.portfolio_repo = PortfolioRepository(self.db)
        self.sources = HoldingsRepository(self.db)
        self.notifier = notifier
        self.context_builder = context_builder

    def list_strategies(self, market: str) -> list[dict[str, str]]:
        return [{"key": item.key, "version": item.version} for item in strategies_for(market)]

    def evaluate_market(self, market: str, *, now: datetime | None = None, uid: int | None = None) -> dict[str, Any]:
        current = now or utc_now()
        uids = [uid] if uid is not None else self._active_uids(market)
        context = self._market_context(market, now=current)
        evaluated = 0
        notified = 0
        positions = 0
        last_context = {
            "market": context.market,
            "regime": context.regime,
            "warnings": list(context.warnings),
        }
        for user in uids:
            result = self.evaluate_uid(user, market=market, now=current, context=context)
            evaluated += 1
            notified += int(result.get("notified") or 0)
            positions += len(result.get("positions") or [])
        return {
            "status": "OK",
            "market": market,
            "users": len(uids),
            "evaluated": evaluated,
            "positions": positions,
            "notified": notified,
            "context_builds": 1,
            "market_context": last_context,
        }

    def evaluate_uid(
        self,
        uid: int,
        *,
        market: str,
        now: datetime | None = None,
        context: MarketContext | None = None,
    ) -> dict[str, Any]:
        current = now or utc_now()
        portfolio = self.resolver.get_resolved_portfolio(uid, market=market)
        context = context or self._market_context(market, now=current)
        eligible = list(portfolio.stock_positions(market))
        symbols = [item.symbol for item in eligible]
        quotes = self.market.quotes(symbols, now=current) if symbols else {}
        start = current - timedelta(days=20)
        bars = self.market.cached_five_minute_bars(symbols, start=start, end=current, now=current) if symbols else {}
        needed = self.market.symbols_needing_refresh(symbols, now=current) if symbols else []
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
            summaries = []
            persistable: list[TradeSignal] = []
            next_states: dict[tuple[str, str, str], dict[str, Any]] = {}
            exit_states: dict[str, dict[str, Any]] = {}
            for position in eligible:
                quality = self.market.bar_quality(position.symbol, now=current)
                position_signals: list[TradeSignal] = []
                for strategy in position_strategies(market):
                    row = self.states.get_state(
                        session,
                        uid=uid,
                        account_id=position.account_id,
                        position_id=position.position_id,
                        strategy_key=strategy.key,
                    )
                    state = deepcopy(row.state) if row is not None and isinstance(row.state, dict) else {}
                    if strategy.key == "exit_v1":
                        produced = strategy.evaluate(
                            position,
                            context,
                            quotes.get(position.symbol),
                            bars.get(position.symbol, []),
                            state,
                            latest_expected=quality.get("latest_expected_closed"),
                            bars_stale=bool(quality.get("stale")),
                            now=current,
                            policy=policy,
                        )
                    else:
                        produced = strategy.evaluate(
                            position,
                            context,
                            quotes.get(position.symbol),
                            bars.get(position.symbol, []),
                            state,
                        )
                    next_states[(position.account_id, position.position_id, strategy.key)] = state
                    if strategy.key == "exit_v1":
                        exit_states[position.position_id] = state
                    position_signals.extend(produced)
                aggregated = aggregate_position_signals(position_signals)
                persistable.extend(item for item in position_signals if should_persist(item))
                summaries.append(
                    {
                        "account_id": position.account_id,
                        "position_id": position.position_id,
                        "symbol": position.symbol,
                        "source": position.source,
                        "action": aggregated.action,
                        "suggested_target_quantity": None
                        if aggregated.suggested_target_quantity is None
                        else format(aggregated.suggested_target_quantity, "f"),
                        "reasons": list(aggregated.reasons),
                        "profit_stage": (exit_states.get(position.position_id) or {}).get("profit_stage"),
                        "active_stop": (exit_states.get(position.position_id) or {}).get("active_stop"),
                    }
                )
            cash = sum((_dec(item.cash) for item in portfolio.accounts if item.market == market), start=Decimal("0"))
            for strategy in portfolio_strategies(market):
                produced = strategy.evaluate(
                    eligible,
                    quotes,
                    context,
                    exit_states,
                    cash=cash,
                    policy=policy,
                )
                persistable.extend(item for item in produced if should_persist(item))
                for item in produced:
                    summaries.append(
                        {
                            "account_id": item.account_id,
                            "position_id": item.position_id,
                            "symbol": item.symbol,
                            "source": "PORTFOLIO",
                            "action": item.action,
                            "suggested_target_quantity": None,
                            "reasons": [item.reason],
                            "profit_stage": None,
                            "active_stop": None,
                        }
                    )
            created: list[TradeSignal] = []
            for signal in persistable:
                if self.states.has_signal(session, uid=uid, signal_key=signal.signal_key):
                    continue
                created.append(signal)
            notification_id = None
            if created:
                title, body = render_trade_message(market=market, signals=created)
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
                    reason=signal.reason,
                    evidence=signal.evidence,
                    signal_key=signal.signal_key,
                    evaluated_at=signal.evaluated_at,
                    notification_id=notification_id,
                )
            for (account_id, position_id, strategy_key), state in next_states.items():
                version = next((item.version for item in position_strategies(market) if item.key == strategy_key), "1")
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
                "status": "OK",
                "positions": summaries,
                "notified": 1 if created else 0,
                "created_signals": len(created),
                "context_builds": 1,
                "market_context": {
                    "market": context.market,
                    "regime": context.regime,
                    "warnings": list(context.warnings),
                },
                "notification_id": notification_id,
                "title_body": render_trade_message(market=market, signals=created) if created else None,
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
                    "evidence": row.evidence or {},
                    "signal_key": row.signal_key,
                    "evaluated_at": row.evaluated_at,
                    "notification_id": row.notification_id,
                    "created_at": row.created_at,
                }
                for row in rows
            ]

    def _market_context(self, market: str, *, now: datetime) -> MarketContext:
        if self.context_builder is not None:
            return self.context_builder(market, now)
        if market == "CN":
            return build_cn_market_context(now=now, db=self.db)
        return build_us_market_context(now=now, db=self.db)

    def _active_uids(self, market: str) -> list[int]:
        with self.db.get_session() as session:
            uids = set(self.portfolio_repo.list_uids_with_open_positions(session, market=market))
        for source in self.sources.list_enabled():
            uids.add(source.uid)
        return sorted(uids)

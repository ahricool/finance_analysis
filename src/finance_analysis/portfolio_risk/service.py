# -*- coding: utf-8 -*-
"""Evaluate holdings against quotes and 5m bars, persist state/events, then push globally."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from finance_analysis.core.time import utc_now  # pragma: allowlist secret
from finance_analysis.database.models.holdings import PositionRiskState  # pragma: allowlist secret
from finance_analysis.database.repositories.holdings import (  # pragma: allowlist secret
    HoldingsRepository,
    PositionRiskStateRepository,
    RiskEventRepository,
)
from finance_analysis.database.session import DatabaseManager  # pragma: allowlist secret
from finance_analysis.holdings.models import HoldingsSnapshot, ParsedPosition  # pragma: allowlist secret
from finance_analysis.holdings.service import HoldingsService  # pragma: allowlist secret
from finance_analysis.integrations.market_data.normalizer import infer_market  # pragma: allowlist secret
from finance_analysis.notification.service import NotificationService  # pragma: allowlist secret
from finance_analysis.portfolio_risk.account import AccountView, apply_account_constraints, merge_account_targets  # pragma: allowlist secret
from finance_analysis.portfolio_risk.config import get_risk_policy  # pragma: allowlist secret
from finance_analysis.portfolio_risk.exits import (  # pragma: allowlist secret
    LegInput,
    PositionInput,
    PositionState,
    QuoteView,
    evaluate_position_exit,
)
from finance_analysis.portfolio_risk.models import ActivePlan, LegsStateDocument  # pragma: allowlist secret
from finance_analysis.portfolio_risk.notify import push_after_commit, render_risk_message  # pragma: allowlist secret
from finance_analysis.portfolio_risk.market import RiskMarketGateway  # pragma: allowlist secret


class PortfolioRiskService:
    def __init__(
        self,
        *,
        holdings: HoldingsService | None = None,
        market: RiskMarketGateway | None = None,
        db: DatabaseManager | None = None,
        notifier: NotificationService | None = None,
    ) -> None:
        self.holdings = holdings or HoldingsService()
        self.market = market or RiskMarketGateway()
        self.db = db or DatabaseManager.get_instance()
        self.sources = HoldingsRepository(self.db)
        self.states = PositionRiskStateRepository(self.db)
        self.events = RiskEventRepository(self.db)
        self.notifier = notifier

    def evaluate_uid(self, uid: int, *, market_filter: str | None = None, now: datetime | None = None) -> dict[str, Any]:
        current = now or utc_now()
        source = self.sources.get_for_uid(uid)
        if source is None or not source.enabled:
            return {"status": "disabled"}
        snapshot = self.holdings.get_snapshot(uid=uid)
        if snapshot is None or snapshot.status != "VALID":
            return {"status": "UNAVAILABLE", "reason": "holdings_unavailable"}
        return self.evaluate_snapshot(snapshot, source_row=source, market_filter=market_filter, now=current)

    def evaluate_snapshot(self, snapshot: HoldingsSnapshot, *, source_row, market_filter: str | None, now: datetime) -> dict[str, Any]:
        policy = get_risk_policy().merge(source_row.risk_policy)
        all_positions: list[ParsedPosition] = []
        refresh_symbols: list[str] = []
        for position in snapshot.positions:
            if not position.canonical_symbol:
                continue
            all_positions.append(position)
            market = infer_market(position.canonical_symbol).value
            if not market_filter or market == market_filter:
                refresh_symbols.append(position.canonical_symbol)
        unique_all = list(dict.fromkeys(item.canonical_symbol for item in all_positions if item.canonical_symbol))
        unique_refresh = list(dict.fromkeys(refresh_symbols))
        quotes = self.market.quotes(unique_all, now=now) if unique_all else {}
        start = now - timedelta(days=20)
        cached_bars = (
            self.market.cached_five_minute_bars(unique_all, start=start, end=now, now=now) if unique_all else {}
        )
        summaries, notify_items = self._persist_evaluations(
            snapshot,
            source_row=source_row,
            positions=all_positions,
            quotes=quotes,
            bars=cached_bars,
            policy=policy,
            now=now,
        )
        if summaries and summaries[0].get("status") in {"stale_source", "stale_generation"}:
            return {"status": summaries[0]["status"]}
        needed = self.market.symbols_needing_refresh(unique_refresh, now=now) if unique_refresh else []
        if needed:
            refreshed = self.market.five_minute_bars(
                needed,
                start=start,
                end=now,
                now=now,
                refresh=True,
                timeout_seconds=policy.five_minute_timeout_seconds,
            )
            bars = dict(cached_bars)
            bars.update(refreshed)
            summaries, extra_notify = self._persist_evaluations(
                snapshot,
                source_row=source_row,
                positions=all_positions,
                quotes=quotes,
                bars=bars,
                policy=policy,
                now=now,
            )
            notify_items.extend(extra_notify)
        return {"status": "OK", "positions": summaries, "notified": len(notify_items)}


    def _persist_evaluations(
        self,
        snapshot: HoldingsSnapshot,
        *,
        source_row,
        positions: list[ParsedPosition],
        quotes,
        bars,
        policy,
        now: datetime,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        existing_map = {
            (row.account_id, row.position_id): row
            for row in self.states.get_for_source(uid=snapshot.uid, source_id=snapshot.source_id)
        }
        holdings_actionable = not any("holdings_stale" in warning for warning in snapshot.warnings)
        computed_rows = []
        by_account: dict[str, list] = {}
        for position in positions:
            symbol = position.canonical_symbol or ""
            quality = self.market.bar_quality(symbol, now=now) if symbol else {"stale": False, "latest_expected_closed": None}
            payload = self._compute_position(
                snapshot=snapshot,
                position=position,
                bars=bars.get(symbol, []),
                quote=quotes.get(symbol),
                existing=existing_map.get((position.account_id, position.position_id)),
                policy=policy,
                now=now,
                bars_stale=bool(quality.get("stale")),
                latest_expected=quality.get("latest_expected_closed"),
                holdings_actionable=holdings_actionable,
            )
            computed_rows.append((position, payload))
            by_account.setdefault(position.account_id, []).append((position, payload))
        accounts = {account.account_id: account for account in snapshot.accounts}
        for account_id, items in by_account.items():
            account = accounts.get(account_id)
            if account is None:
                continue
            view = AccountView(
                account_id=account.account_id,
                base_currency=account.base_currency,
                net_asset=account.net_asset,
                nav_evaluable=account.validity == "VALID",
            )
            ready = [
                (self._position_input(position), result["computed"], quotes.get(position.canonical_symbol or ""))
                for position, result in items
                if result.get("computed") is not None
            ]
            if not ready:
                continue
            constraints = apply_account_constraints(
                account=view,
                positions=ready,
                policy=policy,
                currencies={
                    position.canonical_symbol or position.symbol: position.currency or account.base_currency
                    for position, _result in items
                },
            )
            for position, result in items:
                risk = constraints.get((position.account_id, position.position_id))
                if risk is None or result.get("computed") is None:
                    continue
                merged = merge_account_targets(self._position_input(position), result["computed"], risk)
                result["computed"] = merged
                result["summary"] = self._summary_from_computed(position, merged, risk)
        summaries = []
        notify_items = []
        pushes: list[tuple[int, str, str]] = []
        with self.db.session_scope() as session:
            source = self.sources.lock_source(session, source_id=snapshot.source_id, uid=snapshot.uid)
            if source is None or source.config_version != source_row.config_version or not source.enabled:
                return [{"status": "stale_source"}], []
            if source.published_generation != snapshot.generation:
                return [{"status": "stale_generation"}], []
            keys = [(item.account_id, item.position_id) for item in positions]
            locked = self.states.lock_many(session, source_id=snapshot.source_id, keys=keys)
            for position, result in computed_rows:
                written = self._write_position(
                    session,
                    snapshot=snapshot,
                    position=position,
                    existing=locked.get((position.account_id, position.position_id)),
                    policy=policy,
                    now=now,
                    computed=result.get("computed"),
                    summary=result["summary"],
                )
                summaries.append(written["summary"])
                notify_items.extend(written.get("notify_items") or [])
            if notify_items:
                title, body = render_risk_message(
                    uid=snapshot.uid, snapshot_generation=snapshot.generation, results=notify_items
                )
                notification_id = self.events.create_notification(
                    session, uid=snapshot.uid, title=title, content=body, route_type="alert", severity="warning"
                )
                for item in notify_items:
                    item["event_row"].notification_id = notification_id
                pushes.append((notification_id, title, body))
        for notification_id, title, body in pushes:
            push_result = push_after_commit(
                notification_id=notification_id, title=title, content=body, service=self.notifier
            )
            push_status = "SENT" if push_result.push_sent else ("SKIPPED" if not push_result.push_attempted else "FAILED")
            with self.db.session_scope() as session:
                self.events.mark_push_status(session, notification_id=notification_id, push_status=push_status)
        return summaries, notify_items

    def _position_input(self, position: ParsedPosition) -> PositionInput:
        return PositionInput(
            account_id=position.account_id,
            position_id=position.position_id,
            symbol=position.canonical_symbol or position.symbol,
            legs=tuple(
                LegInput(
                    leg_id=leg.leg_id,
                    role=leg.leg_role,
                    quantity=leg.quantity,
                    entry_price=leg.entry_price,
                    entry_time=leg.entry_time,
                    initial_stop=leg.initial_stop,
                    coverage=leg.coverage,
                    available_quantity=leg.available_quantity,
                    available_as_of=leg.available_as_of,
                )
                for leg in position.legs
                if leg.status == "OPEN"
            ),
        )

    def _compute_position(
        self,
        *,
        snapshot: HoldingsSnapshot,
        position: ParsedPosition,
        bars,
        quote: QuoteView | None,
        existing: PositionRiskState | None,
        policy,
        now: datetime,
        bars_stale: bool,
        latest_expected,
        holdings_actionable: bool,
    ) -> dict[str, Any]:
        legs_input = self._position_input(position)
        if not legs_input.legs:
            close_pending = bool(existing and existing.plan_status == "PENDING")
            return {
                "summary": {
                    "account_id": position.account_id,
                    "position_id": position.position_id,
                    "symbol": position.canonical_symbol,
                    "action": "HOLD",
                    "status": "CLOSED",
                    "close_pending": close_pending,
                },
                "computed": None,
                "close_pending": close_pending,
            }
        computed = evaluate_position_exit(
            legs_input,
            quote=quote,
            bars=bars,
            state=_state_from_row(existing),
            policy=policy,
            now=now,
            market=infer_market(position.canonical_symbol or position.symbol).value,
            latest_expected=latest_expected,
            bars_stale=bars_stale,
            holdings_actionable=holdings_actionable,
        )
        return {"summary": self._summary_from_computed(position, computed, None), "computed": computed}

    def _summary_from_computed(self, position, computed, risk) -> dict[str, Any]:
        payload = {
            "account_id": position.account_id,
            "position_id": position.position_id,
            "symbol": position.canonical_symbol,
            "action": computed.plan.action,
            "plan_status": computed.plan.status,
            "position_target": format(computed.position_target, "f"),
            "current_quantity": format(sum((leg.quantity for leg in position.legs if leg.status == "OPEN"), start=Decimal("0")), "f"),
            "reduce_quantity": format(computed.reduce_quantity, "f"),
            "quote_status": computed.quote_status,
            "five_minute_status": computed.five_minute_status,
            "needs_review": computed.needs_review,
            "reasons": list(computed.reasons),
            "evidence": computed.evidence,
            "legs": [
                {
                    "leg_id": item.leg_id,
                    "target": format(item.target_quantity, "f"),
                    "reason": item.reason,
                    "stage": item.stage,
                    "active_stop": None if item.active_stop is None else format(item.active_stop, "f"),
                    "hard_exit": item.hard_exit,
                }
                for item in computed.leg_exits
            ],
        }
        if risk is not None:
            payload["account_unmet"] = list(risk.unmet)
            payload["uncovered_risk"] = risk.uncovered_risk
            payload["current_risk"] = None if risk.current_risk is None else format(risk.current_risk, "f")
            payload["post_plan_risk"] = None if risk.post_plan_risk is None else format(risk.post_plan_risk, "f")
            payload["execution"] = risk.execution
            payload["account_complete"] = risk.account_complete
        return payload

    def _write_position(
        self,
        session: Session,
        *,
        snapshot: HoldingsSnapshot,
        position: ParsedPosition,
        existing: PositionRiskState | None,
        policy,
        now: datetime,
        computed,
        summary: dict[str, Any],
    ) -> dict[str, Any]:
        if computed is None:
            if existing is not None and summary.get("close_pending") or (existing is not None and existing.plan_status == "PENDING" and summary.get("status") == "CLOSED"):
                plan = dict(existing.active_plan or {})
                plan["status"] = "SATISFIED_BY_SHEET"
                existing.active_plan = plan
                existing.plan_status = "SATISFIED_BY_SHEET"
                existing.row_version = int(existing.row_version) + 1
                self.events.add(
                    session,
                    uid=snapshot.uid,
                    source_id=snapshot.source_id,
                    account_id=position.account_id,
                    position_id=position.position_id,
                    event_type="PLAN_SATISFIED",
                    rule_version=existing.rule_version,
                    action="HOLD",
                    dedupe_key=f"{snapshot.source_id}|{position.account_id}|{position.position_id}|{existing.plan_revision}|PLAN_SATISFIED|close",
                    evidence={"reason": "last_leg_closed"},
                )
            return {"summary": summary, "notify_items": []}
        row = existing
        if row is None:
            row = PositionRiskState(
                uid=snapshot.uid,
                source_id=snapshot.source_id,
                account_id=position.account_id,
                position_id=position.position_id,
                symbol=position.symbol,
                canonical_symbol=position.canonical_symbol,
            )
            session.add(row)
            session.flush()
        row.row_version = int(row.row_version or 1) + 1
        row.rule_version = policy.rule_version
        row.last_bar_end = computed.state.last_bar_end
        row.last_quote_as_of = computed.quote_as_of
        row.weak_streak = computed.state.weak_streak
        row.recovery_streak = computed.state.recovery_streak
        row.episode_id = computed.state.episode_id
        row.plan_status = computed.plan.status
        row.plan_action = computed.plan.action
        row.plan_revision = computed.plan.revision
        row.active_plan = computed.plan.model_dump(mode="json")
        row.legs_state = LegsStateDocument(
            last_vwap_mode=computed.state.last_vwap_mode,
            episode_consumed=computed.state.episode_consumed,
            needs_review=computed.state.needs_review,
            five_minute_status=computed.five_minute_status,
            quote_status=computed.quote_status,
            legs=computed.state.legs,
        ).model_dump(mode="json")
        row.updated_at = now
        notify_items = []
        for event in computed.events:
            dedupe = "|".join(
                [
                    str(snapshot.source_id),
                    position.account_id,
                    position.position_id,
                    str(event.get("episode_id") or ""),
                    str(event.get("plan_revision") or 0),
                    event["event_type"],
                ]
            )
            if self.events.has_dedupe(session, uid=snapshot.uid, dedupe_key=dedupe):
                continue
            event_row = self.events.add(
                session,
                uid=snapshot.uid,
                source_id=snapshot.source_id,
                account_id=position.account_id,
                position_id=position.position_id,
                event_type=event["event_type"],
                rule_version=policy.rule_version,
                action=event["action"],
                dedupe_key=dedupe,
                episode_id=event.get("episode_id"),
                plan_revision=event.get("plan_revision"),
                target_quantity=computed.position_target,
                evidence=computed.evidence,
                data_time=computed.evaluated_bar_end,
            )
            notify_items.append(
                {
                    "symbol": position.canonical_symbol,
                    "account_id": position.account_id,
                    "position_id": position.position_id,
                    "action": computed.plan.action,
                    "position_target": format(computed.position_target, "f"),
                    "reason": ";".join(computed.reasons),
                    "vwap_mode": computed.evidence.get("vwap_mode"),
                    "legs": [
                        {
                            "leg_id": item.leg_id,
                            "role": next(leg.role for leg in computed.state.legs.values() if leg.leg_id == item.leg_id),
                            "quantity": format(next(leg.quantity for leg in self._position_input(position).legs if leg.leg_id == item.leg_id), "f"),
                            "target": format(item.target_quantity, "f"),
                            "active_stop": None if item.active_stop is None else format(item.active_stop, "f"),
                            "stage": item.stage,
                        }
                        for item in computed.leg_exits
                    ],
                    "event_row": event_row,
                }
            )
        return {"summary": summary, "notify_items": notify_items}

    def latest_view(self, uid: int) -> dict[str, Any]:
        source = self.sources.get_for_uid(uid)
        snapshot = self.holdings.get_snapshot(uid=uid)
        states = self.states.get_for_source(uid=uid, source_id=source.id) if source else []
        events = self.events.list_for_source(uid=uid, source_id=source.id) if source else []
        return {
            "source": None if source is None else {"id": source.id, "generation": source.published_generation, "enabled": source.enabled, "config_version": source.config_version},
            "snapshot": None if snapshot is None else snapshot.model_dump(mode="json"),
            "positions": [
                {
                    "account_id": row.account_id,
                    "position_id": row.position_id,
                    "symbol": row.canonical_symbol or row.symbol,
                    "plan_status": row.plan_status,
                    "plan_action": row.plan_action,
                    "plan_revision": row.plan_revision,
                    "row_version": row.row_version,
                    "last_bar_end": None if row.last_bar_end is None else row.last_bar_end.isoformat(),
                    "last_quote_as_of": None if row.last_quote_as_of is None else row.last_quote_as_of.isoformat(),
                    "active_plan": row.active_plan,
                    "legs_state": row.legs_state,
                    "five_minute_status": (row.legs_state or {}).get("five_minute_status"),
                    "quote_status": (row.legs_state or {}).get("quote_status"),
                    "execution": (row.active_plan or {}).get("execution"),
                    "current_quantity": (row.active_plan or {}).get("current_quantity"),
                    "reduce_quantity": (row.active_plan or {}).get("reduce_quantity"),
                    "needs_review": bool((row.legs_state or {}).get("needs_review")),
                }
                for row in states
            ],
            "events": [
                {
                    "id": row.id,
                    "event_type": row.event_type,
                    "action": row.action,
                    "position_id": row.position_id,
                    "account_id": row.account_id,
                    "leg_id": row.leg_id,
                    "target_quantity": None if row.target_quantity is None else format(row.target_quantity, "f"),
                    "created_at": row.created_at.isoformat(),
                    "notification_id": row.notification_id,
                    "push_status": row.push_status,
                    "evidence": row.evidence,
                }
                for row in events
            ],
        }

    def cancel_plan(self, *, uid: int, account_id: str, position_id: str, expected_state_version: int, reason: str) -> dict[str, Any]:
        with self.db.session_scope() as session:
            source = self.sources.get_for_uid(uid)
            if source is None:
                raise KeyError("source")
            locked = self.states.lock_many(session, source_id=source.id, keys=[(account_id, position_id)])
            row = locked.get((account_id, position_id))
            if row is None or row.uid != uid:
                raise KeyError("position")
            if int(row.row_version) != expected_state_version:
                raise ValueError("state_version_conflict")
            plan = dict(row.active_plan or {})
            plan["status"] = "CANCELED"
            plan["reason"] = reason
            row.active_plan = plan
            row.plan_status = "CANCELED"
            row.row_version = int(row.row_version) + 1
            document = LegsStateDocument.model_validate(row.legs_state or {"legs": {}})
            document.episode_consumed = True
            row.legs_state = document.model_dump(mode="json")
            self.events.add(
                session,
                uid=uid,
                source_id=source.id,
                account_id=account_id,
                position_id=position_id,
                event_type="PLAN_CANCELED",
                rule_version=row.rule_version,
                action="HOLD",
                dedupe_key=f"{source.id}|{account_id}|{position_id}|{row.plan_revision}|PLAN_CANCELED|{row.row_version}",
                evidence={"reason": reason},
            )
            return {"plan_status": "CANCELED", "row_version": row.row_version}

    def rebase(
        self,
        *,
        uid: int,
        account_id: str,
        position_id: str,
        leg_id: str,
        expected_source_version: int,
        expected_state_version: int,
        reason: str,
        **fields: Any,
    ) -> dict[str, Any]:
        with self.db.session_scope() as session:
            source = self.sources.lock_source(session, source_id=self.sources.get_for_uid(uid).id, uid=uid)
            if source.config_version != expected_source_version:
                raise ValueError("source_version_conflict")
            locked = self.states.lock_many(session, source_id=source.id, keys=[(account_id, position_id)])
            row = locked.get((account_id, position_id))
            if row is None:
                raise KeyError("position")
            if int(row.row_version) != expected_state_version:
                raise ValueError("state_version_conflict")
            document = LegsStateDocument.model_validate(row.legs_state or {"legs": {}})
            leg = document.legs.get(leg_id)
            if leg is None:
                raise KeyError("leg")
            updates = {key: value for key, value in fields.items() if value is not None}
            if "high_watermark" in updates:
                updates["high_watermark"] = Decimal(str(updates["high_watermark"]))
            if "active_stop" in updates:
                updates["active_stop"] = Decimal(str(updates["active_stop"]))
            updates["rebase_status"] = "PENDING_CONFIRM"
            updates["calibration_required"] = False
            document.legs[leg_id] = leg.model_copy(update=updates)
            row.legs_state = document.model_dump(mode="json")
            row.row_version = int(row.row_version) + 1
            self.events.add(
                session,
                uid=uid,
                source_id=source.id,
                account_id=account_id,
                position_id=position_id,
                leg_id=leg_id,
                event_type="REBASE",
                rule_version=row.rule_version,
                action="HOLD",
                dedupe_key=f"{source.id}|{account_id}|{position_id}|{leg_id}|REBASE|{row.row_version}",
                evidence={"reason": reason, "fields": sorted(updates)},
            )
            return {"row_version": row.row_version, "leg_id": leg_id, "rebase_status": "PENDING_CONFIRM"}


def _state_from_row(row: PositionRiskState | None) -> PositionState:
    if row is None:
        return PositionState()
    document = LegsStateDocument.model_validate(row.legs_state or {"schema_version": "legs_state.v1", "legs": {}})
    plan = ActivePlan.model_validate(row.active_plan) if row.active_plan else ActivePlan()
    return PositionState(
        row_version=row.row_version,
        rule_version=row.rule_version,
        weak_streak=row.weak_streak,
        recovery_streak=row.recovery_streak,
        episode_id=row.episode_id,
        episode_consumed=bool(document.episode_consumed),
        needs_review=bool(document.needs_review),
        last_bar_end=row.last_bar_end,
        last_vwap_mode=document.last_vwap_mode,
        plan=plan,
        legs=document.legs,
    )

"""Explicit transactional state changes; exchange payloads are immutable identifiers."""

import time
import uuid
from datetime import timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from finance_analysis.core.time import utc_now
from finance_analysis.database import DatabaseManager
from finance_analysis.integrations.crypto.account_records import normalize_ids, equity_history_point
from finance_analysis.database.models.paper_trade import (
    PaperAccountSnapshot,
    PaperExchangeRecord,
    PaperIntent,
    PaperStrategy,
    PaperTradeControl,
)


def session_scope():
    return DatabaseManager.get_instance().session_scope()


def trade_control_dict(row):
    return {
        "enabled": bool(row and row.enabled),
        "updated_at": row.updated_at.replace(tzinfo=timezone.utc).isoformat() if row else None,
    }


def trade_control():
    with session_scope() as s:
        return trade_control_dict(s.get(PaperTradeControl, 1))


def locked_trade_control(s):
    s.execute(
        insert(PaperTradeControl)
        .values(id=1, enabled=False, updated_at=utc_now())
        .on_conflict_do_nothing(index_elements=["id"])
    )
    return s.get(PaperTradeControl, 1, with_for_update=True)


def bind_account(alias):
    """Bind before storing private facts; a partial first sync cannot mix accounts."""
    if not alias:
        raise ValueError("DEMO_ACCOUNT_ID_UNAVAILABLE")
    with session_scope() as s:
        row = locked_trade_control(s)
        # A previously installed 0097 may have already stored snapshots.
        previous = s.scalar(select(PaperAccountSnapshot).order_by(PaperAccountSnapshot.id.desc()).limit(1))
        old_alias = row.account_alias or (previous.payload.get("account_alias") if previous else None)
        if old_alias and old_alias != alias:
            raise ValueError("DEMO_ACCOUNT_CHANGED")
        row.account_alias = alias


def opens_position(action, payload):
    return action == "SIGNAL" or (action == "MANUAL" and payload.get("reduce_only") is not True)


def set_trade_control(enabled):
    with session_scope() as s:
        row = locked_trade_control(s)
        if row.enabled != enabled:
            row.enabled, row.updated_at = enabled, utc_now()
            for strategy in s.scalars(select(PaperStrategy).with_for_update()):
                strategy.cursor = max(strategy.cursor, int(time.time() * 1000) // 300_000 * 300_000)
            if not enabled:
                for intent in s.scalars(select(PaperIntent).where(PaperIntent.status == "QUEUED").with_for_update()):
                    if opens_position(intent.action, intent.payload):
                        intent.status, intent.reason, intent.updated_at = (
                            "BLOCKED",
                            "GLOBAL_TRADING_DISABLED",
                            utc_now(),
                        )
        return trade_control_dict(row)


def strategy_dict(row):
    return {
        "symbol": row.symbol,
        **row.config,
        "enabled": row.enabled,
        "cursor": row.cursor,
        "status": row.status,
        "updated_at": row.updated_at.replace(tzinfo=timezone.utc).isoformat(),
    }


def intent_dict(row):
    return {
        field: getattr(row, field)
        for field in ("id", "symbol", "strategy", "bar_time", "action", "payload", "status", "reason")
    } | {
        "created_at": row.created_at.replace(tzinfo=timezone.utc).isoformat(),
        "updated_at": row.updated_at.replace(tzinfo=timezone.utc).isoformat(),
    }


def strategies():
    with session_scope() as s:
        return [strategy_dict(row) for row in s.scalars(select(PaperStrategy).order_by(PaperStrategy.symbol))]


def save_strategy(symbol, config):
    with session_scope() as s:
        row = s.get(PaperStrategy, symbol, with_for_update=True)
        if row and row.enabled:
            raise ValueError("PAUSE_STRATEGY_FIRST")
        if row and s.scalar(
            select(PaperIntent.id)
            .where(
                PaperIntent.strategy == symbol,
                PaperIntent.status.in_(["QUEUED", "SUBMITTING", "UNKNOWN", "SUBMITTED", "PARTIALLY_FILLED"]),
            )
            .limit(1)
        ):
            raise ValueError("STRATEGY_HAS_PENDING_ORDER")
        if row is None:
            row = PaperStrategy(symbol=symbol, enabled=False, cursor=0, status="PAUSED", config=config)
            s.add(row)
        else:
            row.config = config
            row.updated_at = utc_now()
        s.flush()
        return strategy_dict(row)


def control(symbol, enabled):
    with session_scope() as s:
        row = s.get(PaperStrategy, symbol, with_for_update=True)
        if row is None:
            raise ValueError("STRATEGY_NOT_FOUND")
        row.enabled = enabled
        row.cursor = max(row.cursor, int(time.time() * 1000) // 300_000 * 300_000)
        row.status = "WAITING" if enabled else "PAUSED"
        if not enabled:
            for intent in s.scalars(
                select(PaperIntent)
                .where(PaperIntent.strategy == symbol, PaperIntent.status == "QUEUED", PaperIntent.action == "SIGNAL")
                .with_for_update()
            ):
                intent.status, intent.reason = "BLOCKED", "PAUSED"
        row.updated_at = utc_now()
        return strategy_dict(row)


def status(symbol, reason):
    with session_scope() as s:
        row = s.get(PaperStrategy, symbol, with_for_update=True)
        if row:
            row.status = reason


def signal(symbol, bar_time, payload, action, reason=None):
    with session_scope() as s:
        global_enabled = locked_trade_control(s).enabled
        row = s.get(PaperStrategy, symbol, with_for_update=True)
        if not row or bar_time <= row.cursor:
            return
        row.cursor = bar_time
        if not action:
            return
        result = (
            "BLOCKED"
            if reason
            else "OBSERVED" if action == "SIGNAL" and (not row.enabled or not global_enabled) else "QUEUED"
        )
        observed_reason = "GLOBAL_TRADING_DISABLED" if not global_enabled else "PAUSED"
        intent = PaperIntent(
            id=uuid.uuid4().hex,
            symbol=symbol,
            strategy=symbol,
            bar_time=bar_time,
            action=action,
            payload=payload,
            status=result,
            reason=reason or (observed_reason if result == "OBSERVED" else None),
        )
        s.add(intent)
        row.status = intent.reason or result
        s.flush()
        return intent_dict(intent)


def queue(intent_id, symbol, action, payload, strategy=None):
    with session_scope() as s:
        if opens_position(action, payload):
            enabled = locked_trade_control(s).enabled
            if not enabled and s.get(PaperIntent, intent_id) is None:
                raise ValueError("GLOBAL_TRADING_DISABLED")
        statement = (
            insert(PaperIntent)
            .values(
                id=intent_id,
                symbol=symbol,
                action=action,
                payload=payload,
                strategy=strategy,
                status="QUEUED",
                created_at=utc_now(),
                updated_at=utc_now(),
            )
            .on_conflict_do_nothing(index_elements=["id"])
        )
        s.execute(statement)
        row = s.get(PaperIntent, intent_id)
        original = {
            k: v for k, v in row.payload.items() if k != "exchange_request" and (k != "algo" or action == "CANCEL")
        }
        if row.symbol != symbol or row.action != action or row.strategy != strategy or original != payload:
            raise ValueError("REQUEST_ID_REUSED")
        return intent_dict(row)


def intents(active=False):
    with session_scope() as s:
        query = select(PaperIntent).order_by(PaperIntent.created_at)
        if active:
            query = query.where(
                PaperIntent.status.in_(["QUEUED", "SUBMITTING", "UNKNOWN", "SUBMITTED", "PARTIALLY_FILLED"])
            )
        return [intent_dict(row) for row in s.scalars(query)]


def transition(intent_id, state, reason=None, payload=None, expected=None):
    with session_scope() as s:
        row = s.get(PaperIntent, intent_id, with_for_update=True)
        if not row or (expected and row.status != expected):
            return False
        row.status, row.reason, row.updated_at = state, reason, utc_now()
        if payload is not None:
            row.payload = payload
        return True


def put_records(kind, rows):
    id_key = {"order": "orderId", "algo": "algoId", "trade": "id", "income": "tranId"}[kind]
    with session_scope() as s:
        for source in rows:
            row = normalize_ids(source)
            stamp = int(row.get("updateTime", row.get("time", row.get("createTime", 0))))
            exchange_id = str(row[id_key])
            if kind == "income":
                exchange_id = f"{row['incomeType']}:{exchange_id}"
            old = s.get(
                PaperExchangeRecord,
                (kind, row.get("symbol") or "", exchange_id),
                with_for_update=True,
                populate_existing=True,
            )
            if old:
                if stamp < old.timestamp:
                    continue
                state_field = "status" if kind == "order" else "algoStatus"
                terminal = {"FILLED", "CANCELED", "EXPIRED", "FINISHED", "REJECTED", "EXPIRED_IN_MATCH"}
                if (
                    kind in {"order", "algo"}
                    and old.payload.get(state_field) in terminal
                    and row.get(state_field) not in terminal
                ):
                    continue
                row = {**old.payload, **row}
            statement = insert(PaperExchangeRecord).values(
                kind=kind,
                symbol=row.get("symbol") or "",
                exchange_id=exchange_id,
                timestamp=stamp,
                payload=row,
            )
            s.execute(
                statement.on_conflict_do_update(
                    index_elements=["kind", "symbol", "exchange_id"],
                    set_={"timestamp": statement.excluded.timestamp, "payload": statement.excluded.payload},
                    where=statement.excluded.timestamp >= PaperExchangeRecord.timestamp,
                )
            )


def get_record(kind, symbol, exchange_id):
    with session_scope() as s:
        row = s.get(PaperExchangeRecord, (kind, symbol, exchange_id))
        return row.payload if row else None


def records(kind):
    with session_scope() as s:
        return [
            row.payload
            for row in s.scalars(
                select(PaperExchangeRecord)
                .where(PaperExchangeRecord.kind == kind)
                .order_by(PaperExchangeRecord.timestamp, PaperExchangeRecord.exchange_id)
            )
        ]


def save_snapshot(payload):
    with session_scope() as s:
        latest = s.scalar(select(PaperAccountSnapshot).order_by(PaperAccountSnapshot.id.desc()).limit(1))
        # Persist bounded cadence of equity points; latest view always advances.
        now = utc_now()
        if latest and (now - latest.observed_at.replace(tzinfo=timezone.utc)).total_seconds() < 60:
            latest.payload = payload
        else:
            if latest:
                latest.payload = equity_history_point(latest.payload)
            s.add(PaperAccountSnapshot(payload=payload, observed_at=now))


def snapshots():
    with session_scope() as s:
        rows = list(s.scalars(select(PaperAccountSnapshot).order_by(PaperAccountSnapshot.id.desc()).limit(1440)))
        return (
            rows[0].payload if rows else None,
            [
                {
                    "time": row.observed_at.replace(tzinfo=timezone.utc).isoformat(),
                    "equity": row.payload.get("account", {}).get("totalMarginBalance"),
                }
                for row in reversed(rows)
            ],
        )


def skip_previous_bars(bar):
    with session_scope() as s:
        for row in s.scalars(select(PaperStrategy).with_for_update()):
            row.cursor = max(row.cursor, bar)
        # Old signals from a previous process are not replayed. An uncertain
        # submission remains in the reconciliation queue, never resubmitted.
        for row in s.scalars(
            select(PaperIntent)
            .where(PaperIntent.status == "QUEUED", PaperIntent.bar_time.is_not(None))
            .with_for_update()
        ):
            row.status, row.reason = "BLOCKED", "RESTARTED"


def claim(intent_id, symbol, action, payload):
    """Atomic control check and durable claim before any exchange side effect."""
    with session_scope() as s:
        global_enabled = locked_trade_control(s).enabled if opens_position(action, payload) else True
        strategy = s.get(PaperStrategy, symbol, with_for_update=True) if action == "SIGNAL" else None
        row = s.get(PaperIntent, intent_id, with_for_update=True)
        if not row or row.status != "QUEUED":
            return False
        if not global_enabled:
            row.status, row.reason = "BLOCKED", "GLOBAL_TRADING_DISABLED"
            return False
        if action == "SIGNAL" and (not strategy or not strategy.enabled):
            row.status, row.reason = "BLOCKED", "PAUSED"
            return False
        row.payload, row.status, row.updated_at = payload, "SUBMITTING", utc_now()
        return True

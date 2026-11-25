"""Live-only persistence with a transactionally audited account-level control."""

from datetime import timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from finance_analysis.core.time import utc_now
from finance_analysis.database import DatabaseManager
from finance_analysis.database.models.live_trade import (
    LiveTradeControl,
    LiveTradeControlEvent,
    LiveAccountSnapshot,
    LiveExchangeRecord,
)
from finance_analysis.integrations.crypto.account_records import normalize_ids, equity_history_point


def session_scope():
    return DatabaseManager.get_instance().session_scope()


def iso(value):
    return value.replace(tzinfo=timezone.utc).isoformat()


def control_dict(row):
    return {"enabled": bool(row and row.enabled), "updated_at": iso(row.updated_at) if row else None}


def control():
    with session_scope() as session:
        return control_dict(session.get(LiveTradeControl, 1))


def locked_control(session):
    session.execute(
        insert(LiveTradeControl)
        .values(id=1, enabled=False, updated_at=utc_now())
        .on_conflict_do_nothing(index_elements=["id"])
    )
    return session.get(LiveTradeControl, 1, with_for_update=True)


def bind(alias):
    if not alias:
        raise ValueError("LIVE_ACCOUNT_ID_UNAVAILABLE")
    with session_scope() as session:
        row = locked_control(session)
        if row.account_alias and row.account_alias != alias:
            raise ValueError("LIVE_ACCOUNT_CHANGED")
        if row.account_alias is None:
            row.account_alias = alias


def set_control(enabled, actor_id):
    with session_scope() as session:
        row = locked_control(session)
        if row.enabled != enabled:
            now = utc_now()
            session.add(LiveTradeControlEvent(actor_id=actor_id, previous=row.enabled, enabled=enabled, changed_at=now))
            row.enabled, row.updated_at = enabled, now
        return control_dict(row)


def events():
    with session_scope() as session:
        return [
            {
                "actor_id": row.actor_id,
                "previous": row.previous,
                "enabled": row.enabled,
                "changed_at": iso(row.changed_at),
            }
            for row in session.scalars(
                select(LiveTradeControlEvent).order_by(LiveTradeControlEvent.id.desc()).limit(200)
            )
        ]


def put_records(kind, rows):
    id_key = {"order": "orderId", "algo": "algoId", "trade": "id", "income": "tranId"}[kind]
    with session_scope() as session:
        for source in rows:
            row = normalize_ids(source)
            symbol = row.get("symbol") or ""
            exchange_id = row[id_key] if kind != "income" else f"{row['incomeType']}:{row[id_key]}"
            stamp = int(row.get("updateTime", row.get("time", row.get("createTime", 0))))
            old = session.get(
                LiveExchangeRecord, (kind, symbol, exchange_id), with_for_update=True, populate_existing=True
            )
            if old:
                state_field = "status" if kind == "order" else "algoStatus"
                terminal = {"FILLED", "CANCELED", "EXPIRED", "EXPIRED_IN_MATCH", "FINISHED", "REJECTED"}
                if stamp < old.timestamp or (
                    kind in {"order", "algo"}
                    and old.payload.get(state_field) in terminal
                    and row.get(state_field) not in terminal
                ):
                    continue
                row = {**old.payload, **row}
            statement = insert(LiveExchangeRecord).values(
                kind=kind, symbol=symbol, exchange_id=exchange_id, timestamp=stamp, payload=row
            )
            session.execute(
                statement.on_conflict_do_update(
                    index_elements=["kind", "symbol", "exchange_id"],
                    set_={"timestamp": statement.excluded.timestamp, "payload": statement.excluded.payload},
                    where=statement.excluded.timestamp >= LiveExchangeRecord.timestamp,
                )
            )


def records(kind, since=None):
    with session_scope() as session:
        query = select(LiveExchangeRecord).where(LiveExchangeRecord.kind == kind)
        if since is not None:
            query = query.where(LiveExchangeRecord.timestamp >= since)
        return [
            row.payload
            for row in session.scalars(
                query.order_by(LiveExchangeRecord.timestamp.desc(), LiveExchangeRecord.exchange_id)
            )
        ]


def save_snapshot(payload):
    with session_scope() as session:
        latest = session.scalar(select(LiveAccountSnapshot).order_by(LiveAccountSnapshot.id.desc()).limit(1))
        now = utc_now()
        if latest and (now - latest.observed_at.replace(tzinfo=timezone.utc)).total_seconds() < 60:
            latest.payload = payload
        else:
            if latest:
                latest.payload = equity_history_point(latest.payload)
            session.add(LiveAccountSnapshot(observed_at=now, payload=payload))


def snapshots():
    with session_scope() as session:
        rows = list(session.scalars(select(LiveAccountSnapshot).order_by(LiveAccountSnapshot.id.desc()).limit(1440)))
        return (
            rows[0].payload if rows else None,
            [
                {"time": iso(row.observed_at), "equity": row.payload.get("account", {}).get("totalMarginBalance")}
                for row in reversed(rows)
            ],
        )

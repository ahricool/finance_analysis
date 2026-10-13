"""Atomic daily documents. PostgreSQL owns both evidence and concurrency control."""

from copy import deepcopy
from datetime import datetime

from sqlalchemy import func, select, tuple_, update
from finance_analysis.core.time import utc_now
from finance_analysis.database.models.intraday_confirmation import IntradayConfirmationSnapshot as Snapshot
from finance_analysis.database.models.stock import Instrument, StockDaily
from finance_analysis.trend_following.preview_cache import json_ready

ANCHOR_FIELDS = (
    "first_confirmed_at", "first_confirmed_price", "first_confirmed_quote_time", "first_confirmation_open",
)
CANDIDATE_FIELDS = (
    "code", "name", "candidate_source", "candidate_trade_date", "candidate_reason", "source_generated_at",
    "official_trend",
)


class StaleConfirmationWrite(RuntimeError):
    pass


def merge_evidence(old, incoming):
    """Frozen membership/provenance and the first anchor never change on later evaluations."""
    by_code = {r["code"]: r for r in incoming["items"]}
    result = deepcopy(old)
    result.update(status=incoming["status"], generated_at=incoming["generated_at"])
    rows = []
    for previous in old["items"]:
        current = by_code.get(previous["code"])
        if current is None:
            raise ValueError("Cannot drop a frozen candidate")
        row = {**previous, **current}
        for key in CANDIDATE_FIELDS:
            if key in previous:
                row[key] = previous[key]
            else:
                row.pop(key, None)
        if previous.get("first_confirmed_at"):
            for key in ANCHOR_FIELDS:
                row[key] = previous.get(key)
        row["return_evidence"] = previous.get("return_evidence", {})
        rows.append(row)
    if len(by_code) != len(rows):
        raise ValueError("Cannot expand a frozen candidate pool")
    result["items"] = rows
    return result


class ConfirmationStore:
    def __init__(self, db_manager=None):
        if db_manager is None:
            from finance_analysis.database.session import DatabaseManager
            db_manager = DatabaseManager.get_instance()
        self.db = db_manager

    def lock(self, market, day):
        from finance_analysis.tasks.advisory_lock import PostgreSQLAdvisoryLock
        # Stable, distinct namespace; one non-expiring lock per market and exchange day.
        namespace = {"CN": 20_261_013, "US": 20_261_014}[market]
        return PostgreSQLAdvisoryLock(day.toordinal(), db_manager=self.db, namespace=namespace)

    @staticmethod
    def serialize(row):
        return {**deepcopy(row.payload), "_revision": row.revision}

    def load(self, market, day):
        with self.db.get_session() as session:
            row = session.get(Snapshot, (market, day))
            return self.serialize(row) if row else None

    def dates(self, market):
        with self.db.get_session() as session:
            return list(session.scalars(
                select(Snapshot.trade_date).where(Snapshot.market == market)
                .order_by(Snapshot.trade_date.desc())
            ))

    def save(self, trading_session, payload):
        market, day = trading_session.market, trading_session.day
        incoming = json_ready({k: v for k, v in payload.items() if k != "_revision"})
        if incoming.get("market") != market or incoming.get("trade_date") != day.isoformat():
            raise ValueError("Snapshot market/date mismatch")
        with self.db.session_scope() as session:
            if payload.get("_revision") is None:
                if incoming["status"] != "frozen":
                    raise ValueError("Only a frozen pool may create a daily snapshot")
                if session.bind.dialect.name == "postgresql":
                    from sqlalchemy.dialects.postgresql import insert
                else:  # Deterministic offline repository tests.
                    from sqlalchemy.dialects.sqlite import insert
                statement = insert(Snapshot).values(
                    market=market, trade_date=day, payload=incoming, revision=1, updated_at=utc_now(),
                    returns_pending=False,
                ).on_conflict_do_nothing(index_elements=["market", "trade_date"])
                session.execute(statement)
            else:
                row = session.get(Snapshot, (market, day), with_for_update=True)
                if row is None or row.revision != payload["_revision"]:
                    raise StaleConfirmationWrite("Daily confirmation changed; retry from persisted evidence")
                if datetime.fromisoformat(incoming["generated_at"]) < datetime.fromisoformat(row.payload["generated_at"]):
                    raise StaleConfirmationWrite("Cannot publish older confirmation evidence")
                merged = merge_evidence(row.payload, incoming)
                # The version predicate also guards callers whose session lock was lost.
                result = session.execute(
                    update(Snapshot).where(
                        Snapshot.market == market, Snapshot.trade_date == day, Snapshot.revision == row.revision,
                    ).values(payload=merged, revision=row.revision + 1, updated_at=utc_now(),
                             returns_pending=self.needs_returns(merged))
                    .execution_options(synchronize_session=False)
                )
                if result.rowcount != 1:
                    raise StaleConfirmationWrite("Concurrent confirmation write")
        return self.load(market, day)

    def load_evaluation_bars(self, pairs):
        if not pairs:
            return []
        query = select(
            Instrument.code, StockDaily.date, StockDaily.open, StockDaily.high,
            StockDaily.low, StockDaily.close, StockDaily.volume, StockDaily.updated_at, StockDaily.data_source,
        ).join(Instrument, Instrument.id == StockDaily.instrument_id).where(
            tuple_(Instrument.code, StockDaily.date).in_(sorted(pairs))
        )
        with self.db.get_session() as session:
            return [dict(row._mapping) for row in session.execute(query)]

    @staticmethod
    def needs_returns(payload):
        return any(
            row.get("first_confirmed_at") and row.get("first_confirmed_price") is not None
            and row.get("first_confirmation_open") is not None and row.get("first_confirmed_quote_time")
            and any(str(n) not in row.get("return_evidence", {}) for n in (3, 5, 10))
            for row in payload["items"]
        )

    def pending_returns(self, market, before, limit=10):
        # Old missing inputs do not starve later days: every checked snapshot moves
        # to the end, even if nothing could be realized. There is no 10-day expiry.
        with self.db.get_session() as session:
            rows = session.scalars(select(Snapshot).where(
                Snapshot.market == market, Snapshot.trade_date < before, Snapshot.returns_pending.is_(True),
            ).order_by(func.coalesce(Snapshot.returns_checked_at, Snapshot.updated_at), Snapshot.trade_date).limit(limit))
            return [self.serialize(row) for row in rows]

    def save_returns(self, market, day, evaluated, checked_at):
        incoming = {row["code"]: row for row in evaluated}
        with self.db.session_scope() as session:
            row = session.get(Snapshot, (market, day), with_for_update=True)
            if row is None:
                return
            payload = deepcopy(row.payload)
            for item in payload["items"]:
                source = incoming.get(item["code"], {})
                # Refuse to attach outcomes computed from a different anchor.
                if any(source.get(key) != item.get(key) for key in ANCHOR_FIELDS):
                    continue
                evidence = item.setdefault("return_evidence", {})
                for horizon, outcome in source.get("return_evidence", {}).items():
                    if horizon in {"3", "5", "10"}:
                        evidence.setdefault(horizon, json_ready(outcome))
            result = session.execute(update(Snapshot).where(
                Snapshot.market == market, Snapshot.trade_date == day, Snapshot.revision == row.revision,
            ).values(payload=payload, revision=row.revision + 1, returns_pending=self.needs_returns(payload),
                     returns_checked_at=checked_at).execution_options(synchronize_session=False))
            if result.rowcount != 1:
                raise StaleConfirmationWrite("Concurrent realized-return write")
            # Keep latest intraday evidence's generated_at/updated_at unchanged.

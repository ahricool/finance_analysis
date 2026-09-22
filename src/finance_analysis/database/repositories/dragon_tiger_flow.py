"""Single-statement window reads and atomic per-day publication; never fetch remotely."""

from uuid import uuid4
from sqlalchemy import select, text
from finance_analysis.core.time import utc_now, coerce_aware_utc, utc_isoformat
from finance_analysis.database.models.dragon_tiger_flow import DragonTigerFlowBatch as Batch
from finance_analysis.dragon_tiger_flow.calendar import sessions_through, expected_date
from finance_analysis.dragon_tiger_flow.calculator import calculate
from finance_analysis.dragon_tiger_flow.config import VERSION, BOARDS


class DragonTigerFlowRepository:
    def __init__(self, db_manager=None):
        if db_manager is None:
            from finance_analysis.database.session import DatabaseManager

            db_manager = DatabaseManager.get_instance()
        self.db = db_manager

    def dates(self):
        with self.db.get_session() as session:
            query = select(
                Batch.trade_date,
                Batch.generated_at,
                Batch.payload["boards"].label("boards"),
                Batch.payload["errors"].label("errors"),
            )
            return [dict(row._mapping) for row in session.execute(query.order_by(Batch.trade_date.desc()))]

    def window(self, end=None, days=20, board="all", period=1):
        with self.db.get_session() as session:
            query = select(Batch).order_by(Batch.trade_date.desc()).limit(1 if period == 3 else days)
            if end is not None:
                query = query.where(Batch.trade_date <= end)
            rows = list(session.scalars(query))
            end = end or (rows[0].trade_date if rows else expected_date())
            dates = sessions_through(end, 1 if period == 3 else days)
            batches = {
                r.trade_date: {**r.payload, "batch_id": r.batch_id, "generated_at": utc_isoformat(r.generated_at)}
                for r in rows
            }
        return calculate(batches, dates, board, period)

    def has_complete(self, day):
        with self.db.get_session() as session:
            row = session.get(Batch, day)
            return row is not None and set(row.payload["sources"]) == set(BOARDS) and not row.payload.get("errors")

    def publish(self, day, sources, errors, collected_at):
        core = sources.get("all")
        if not core or core["trade_date"] != day.isoformat() or any(r["net_value"] is None for r in core["rows"]):
            raise ValueError("Complete core data required; previous batch retained")
        if any(s["trade_date"] != day.isoformat() for s in sources.values()):
            raise ValueError("Mismatched source dates")
        now = utc_now()
        with self.db.session_scope() as session:
            if session.bind.dialect.name == "postgresql":
                session.execute(text("SELECT pg_advisory_xact_lock(964000001)"))
            existing = session.get(Batch, day)
            # Reject stale concurrent collectors and any downgrade of previously available sources.
            if existing:
                if coerce_aware_utc(existing.collected_at) > collected_at:
                    return {"status": "superseded", "trade_date": day.isoformat()}
                if not set(existing.payload["sources"]).issubset(sources):
                    raise ValueError("Source coverage regression; previous batch retained")
            session.merge(
                Batch(
                    trade_date=day,
                    batch_id=str(uuid4()),
                    rule_version=VERSION,
                    collected_at=collected_at,
                    generated_at=now,
                    payload={"sources": sources, "boards": sorted(sources), "errors": errors},
                )
            )
        return {"status": "partial" if errors else "completed", "trade_date": day.isoformat(), "errors": errors}

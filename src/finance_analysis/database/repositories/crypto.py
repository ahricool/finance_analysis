"""Crypto SQL and atomic state/snapshot transitions."""

from contextlib import contextmanager, suppress
from dataclasses import asdict
from datetime import datetime

from sqlalchemy import func, select, text
from sqlalchemy.dialects.postgresql import insert

from finance_analysis.core.time import coerce_aware_utc, utc_now
from finance_analysis.crypto.models import Kline, StrategyState
from finance_analysis.database.models.crypto import CryptoKline, CryptoStrategySnapshot, CryptoStrategyState


def values(row):
    result = {column.name: getattr(row, column.name) for column in row.__table__.columns}
    return {key: coerce_aware_utc(value) if isinstance(value, datetime) else value for key, value in result.items()}


class CryptoLeadershipLost(RuntimeError):
    """The dedicated lock connection was lost; reopen the writer before ingesting."""


class CryptoRepository:
    def __init__(self, db_manager=None):
        if db_manager is None:
            from finance_analysis.database.session import DatabaseManager

            db_manager = DatabaseManager.get_instance()
        self.db = db_manager
        self._leader_session = None

    def upsert_klines(self, rows: list[Kline], as_of: datetime) -> int:
        self._check_leader()
        closed = {row.open_time: row.storage_values() for row in rows if row.closed and row.close_time <= as_of}
        if not closed:
            return 0
        with self.db.session_scope() as session:
            statement = insert(CryptoKline).values(list(closed.values()))
            session.execute(
                statement.on_conflict_do_update(
                    index_elements=["symbol", "interval", "open_time"],
                    set_={
                        **{
                            key: getattr(statement.excluded, key)
                            for key in next(iter(closed.values()))
                            if key not in {"symbol", "interval", "open_time"}
                        },
                        "updated_at": utc_now(),
                    },
                )
            )
        return len(closed)

    def latest_open_time(self):
        with self.db.get_session() as session:
            value = session.scalar(select(func.max(CryptoKline.open_time)).where(CryptoKline.symbol == "BTCUSDT"))
            return coerce_aware_utc(value) if value else None

    def klines(self, *, limit=1000, as_of=None, start=None) -> list[Kline]:
        query = select(CryptoKline).where(CryptoKline.symbol == "BTCUSDT", CryptoKline.interval == "1m")
        query = query.where(CryptoKline.close_time <= (as_of or utc_now()))
        if start is not None:
            query = query.where(CryptoKline.open_time >= start)
        with self.db.get_session() as session:
            rows = session.scalars(query.order_by(CryptoKline.open_time.desc()).limit(limit)).all()
            return [
                Kline(**{k: v for k, v in values(row).items() if k not in {"id", "created_at", "updated_at"}})
                for row in reversed(rows)
            ]

    def signals(self, limit=50):
        with self.db.get_session() as session:
            return [
                values(row)
                for row in session.scalars(
                    select(CryptoStrategySnapshot)
                    .where(CryptoStrategySnapshot.symbol == "BTCUSDT")
                    .order_by(CryptoStrategySnapshot.evaluated_at.desc())
                    .limit(limit)
                )
            ]

    def state(self):
        with self.db.get_session() as session:
            row = session.get(CryptoStrategyState, "BTCUSDT")
            return StrategyState(**values(row)) if row else StrategyState()

    def evaluate_once(self, at: datetime, calculate):
        """Serialize evaluations, refuse replays, commit state and immutable snapshot together."""
        self._check_leader()
        with self.db.session_scope() as session:
            session.execute(
                insert(CryptoStrategyState)
                .values(symbol="BTCUSDT", position_state="FLAT")
                .on_conflict_do_nothing(index_elements=["symbol"])
            )
            row = session.scalar(
                select(CryptoStrategyState).where(CryptoStrategyState.symbol == "BTCUSDT").with_for_update()
            )
            latest = session.scalar(
                select(func.max(CryptoStrategySnapshot.evaluated_at)).where(CryptoStrategySnapshot.symbol == "BTCUSDT")
            )
            if latest and coerce_aware_utc(latest) >= at:
                return None
            result = calculate(StrategyState(**values(row)))
            if result is None:
                return None
            state, snapshot = result
            for key, value in asdict(state).items():
                setattr(row, key, value)
            session.add(CryptoStrategySnapshot(**snapshot))
            return snapshot

    def _check_leader(self):
        if self._leader_session is not None:
            try:
                self._leader_session.execute(text("SELECT 1"))
            except Exception as exc:
                raise CryptoLeadershipLost("BTC writer lock connection lost") from exc

    @contextmanager
    def stream_leader(self):
        """A dedicated PostgreSQL session owns the single BTC writer until shutdown."""
        with self.db.get_session() as session:
            acquired = session.scalar(text("SELECT pg_try_advisory_lock(7310044)"))
            if acquired:
                self._leader_session = session
            try:
                yield bool(acquired)
            finally:
                if acquired:
                    self._leader_session = None
                    with suppress(Exception):
                        session.execute(text("SELECT pg_advisory_unlock(7310044)"))

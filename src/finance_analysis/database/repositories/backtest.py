"""Transactional persistence for backtest runs and normalized results."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, insert, select, update

from finance_analysis.backtest.types import BacktestResult
from finance_analysis.core.time import utc_now
from finance_analysis.database.models.backtest import BacktestEquity, BacktestRun, BacktestTrade


class BacktestRepository:
    def __init__(self, db_manager=None):
        if db_manager is None:
            from finance_analysis.database.session import DatabaseManager

            db_manager = DatabaseManager.get_instance()
        self.db = db_manager

    def create_run(self, values: dict[str, Any]) -> BacktestRun:
        with self.db.session_scope() as session:
            run = BacktestRun(**values)
            session.add(run)
            session.flush()
            session.refresh(run)
            session.expunge(run)
            return run

    def set_task_id(self, run_id: int, task_id: str) -> None:
        with self.db.session_scope() as session:
            session.execute(update(BacktestRun).where(BacktestRun.id == run_id).values(task_id=task_id))

    def claim_run(self, run_id: int) -> BacktestRun | None:
        with self.db.session_scope() as session:
            row = session.execute(
                update(BacktestRun)
                .where(BacktestRun.id == run_id, BacktestRun.status == "pending")
                .values(status="processing", progress=10, started_at=utc_now(), error=None)
                .returning(BacktestRun)
            ).scalar_one_or_none()
            if row is not None:
                session.expunge(row)
            return row

    def update_progress(self, run_id: int, progress: int) -> None:
        with self.db.session_scope() as session:
            session.execute(
                update(BacktestRun)
                .where(BacktestRun.id == run_id, BacktestRun.status == "processing")
                .values(progress=max(0, min(100, progress)))
            )

    def complete_run(self, run_id: int, result: BacktestResult) -> None:
        trades = [
            {
                "run_id": run_id,
                "symbol_id": None,
                **item.__dict__,
            }
            for item in result.trades
        ]
        equities = [{"run_id": run_id, **item.__dict__} for item in result.equity_curve]
        for item in equities:
            item.pop("position_pct", None)
        with self.db.session_scope() as session:
            run = session.execute(select(BacktestRun).where(BacktestRun.id == run_id)).scalar_one()
            symbol_id = run.symbol_id
            for item in trades:
                item["symbol_id"] = symbol_id
            session.execute(delete(BacktestTrade).where(BacktestTrade.run_id == run_id))
            session.execute(delete(BacktestEquity).where(BacktestEquity.run_id == run_id))
            if trades:
                session.execute(insert(BacktestTrade), trades)
            if equities:
                session.execute(insert(BacktestEquity), equities)
            session.execute(
                update(BacktestRun)
                .where(BacktestRun.id == run_id, BacktestRun.status == "processing")
                .values(
                    engine_version=result.engine_version,
                    engine_config={**(run.engine_config or {}), "debug": result.engine_debug},
                    summary=result.summary,
                    warnings=result.warnings,
                    status="completed",
                    progress=100,
                    finished_at=utc_now(),
                    error=None,
                )
            )

    def fail_run(self, run_id: int, error: str) -> None:
        with self.db.session_scope() as session:
            session.execute(
                update(BacktestRun)
                .where(BacktestRun.id == run_id, BacktestRun.status.in_(("pending", "processing")))
                .values(status="failed", progress=100, error=error[:24000], finished_at=utc_now())
            )

    def get_run(self, run_id: int, *, uid: int | None = None, is_admin: bool = False) -> BacktestRun | None:
        with self.db.get_session() as session:
            query = select(BacktestRun).where(BacktestRun.id == run_id)
            if not is_admin:
                query = query.where(BacktestRun.uid == uid)
            row = session.execute(query).scalar_one_or_none()
            if row is not None:
                session.expunge(row)
            return row

    def list_runs(
        self,
        *,
        uid: int,
        is_admin: bool,
        page: int,
        page_size: int,
        filters: dict[str, Any],
    ) -> tuple[list[BacktestRun], int]:
        clauses = []
        if not is_admin:
            clauses.append(BacktestRun.uid == uid)
        elif filters.get("uid") is not None:
            clauses.append(BacktestRun.uid == filters["uid"])
        for key in ("engine", "strategy_key", "market", "code", "status"):
            if filters.get(key):
                clauses.append(getattr(BacktestRun, key) == filters[key])
        if filters.get("created_from"):
            clauses.append(BacktestRun.created_at >= filters["created_from"])
        if filters.get("created_to"):
            clauses.append(BacktestRun.created_at <= filters["created_to"])
        with self.db.get_session() as session:
            total = session.execute(select(func.count(BacktestRun.id)).where(*clauses)).scalar_one()
            rows = list(
                session.execute(
                    select(BacktestRun)
                    .where(*clauses)
                    .order_by(BacktestRun.created_at.desc(), BacktestRun.id.desc())
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                ).scalars().all()
            )
            for row in rows:
                session.expunge(row)
            return rows, total

    def list_trades(
        self, run_id: int, *, uid: int, is_admin: bool, page: int, page_size: int
    ) -> tuple[list[BacktestTrade], int] | None:
        if self.get_run(run_id, uid=uid, is_admin=is_admin) is None:
            return None
        with self.db.get_session() as session:
            total = session.execute(
                select(func.count(BacktestTrade.id)).where(BacktestTrade.run_id == run_id)
            ).scalar_one()
            rows = list(
                session.execute(
                    select(BacktestTrade)
                    .where(BacktestTrade.run_id == run_id)
                    .order_by(BacktestTrade.trade_date, BacktestTrade.id)
                    .offset((page - 1) * page_size)
                    .limit(page_size)
                ).scalars().all()
            )
            for row in rows:
                session.expunge(row)
            return rows, total

    def list_equity(self, run_id: int, *, uid: int, is_admin: bool) -> list[BacktestEquity] | None:
        if self.get_run(run_id, uid=uid, is_admin=is_admin) is None:
            return None
        with self.db.get_session() as session:
            rows = list(
                session.execute(
                    select(BacktestEquity)
                    .where(BacktestEquity.run_id == run_id)
                    .order_by(BacktestEquity.trading_date)
                ).scalars().all()
            )
            for row in rows:
                session.expunge(row)
            return rows

    def delete_run(self, run_id: int, *, uid: int, is_admin: bool) -> bool:
        with self.db.session_scope() as session:
            clauses = [BacktestRun.id == run_id, BacktestRun.status != "processing"]
            if not is_admin:
                clauses.append(BacktestRun.uid == uid)
            return bool(session.execute(delete(BacktestRun).where(*clauses)).rowcount)


__all__ = ["BacktestRepository"]

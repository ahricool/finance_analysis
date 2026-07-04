# -*- coding: utf-8 -*-
"""Repositories for canonical symbols and raw historical market data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import desc, func, literal_column, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from finance_analysis.core.time import utc_now
from finance_analysis.database.models.stock import (
    MarketDataSymbol,
    StockDaily,
    StockMinute,
    validate_market_data_code,
)


@dataclass(frozen=True)
class UpsertStats:
    inserted_rows: int = 0
    updated_rows: int = 0
    skipped_lower_priority_rows: int = 0

    @property
    def affected_rows(self) -> int:
        return self.inserted_rows + self.updated_rows


class MarketDataSymbolRepository:
    def __init__(self, db_manager=None):
        if db_manager is None:
            from finance_analysis.database.session import DatabaseManager

            db_manager = DatabaseManager.get_instance()
        self.db = db_manager

    def get_by_code(self, code: str) -> Optional[MarketDataSymbol]:
        canonical = str(code or "").strip().upper()
        with self.db.get_session() as session:
            row = session.execute(
                select(MarketDataSymbol).where(MarketDataSymbol.code == canonical)
            ).scalar_one_or_none()
            if row is not None:
                session.expunge(row)
            return row

    def list_enabled_daily_symbols(self, market: str) -> list[MarketDataSymbol]:
        return self._list_enabled(market, MarketDataSymbol.sync_daily)

    def list_enabled_minute_symbols(self, market: str) -> list[MarketDataSymbol]:
        return self._list_enabled(market, MarketDataSymbol.sync_minute)

    def list_enabled_symbols(self, market: str) -> list[MarketDataSymbol]:
        normalized = str(market).upper()
        with self.db.get_session() as session:
            rows = session.execute(
                select(MarketDataSymbol)
                .where(MarketDataSymbol.market == normalized, MarketDataSymbol.enabled.is_(True))
                .order_by(MarketDataSymbol.code)
            ).scalars().all()
            for row in rows:
                session.expunge(row)
            return list(rows)

    def search_enabled_symbols(self, market: str, keyword: str = "", limit: int = 20) -> list[MarketDataSymbol]:
        normalized = str(market).upper()
        needle = str(keyword or "").strip()
        with self.db.get_session() as session:
            query = select(MarketDataSymbol).where(
                MarketDataSymbol.market == normalized,
                MarketDataSymbol.enabled.is_(True),
                MarketDataSymbol.sync_daily.is_(True),
            )
            if needle:
                pattern = f"%{needle}%"
                query = query.where(
                    or_(MarketDataSymbol.code.ilike(pattern), MarketDataSymbol.name.ilike(pattern))
                )
            rows = session.execute(query.order_by(MarketDataSymbol.code).limit(limit)).scalars().all()
            for row in rows:
                session.expunge(row)
            return list(rows)

    def _list_enabled(self, market: str, sync_column) -> list[MarketDataSymbol]:
        normalized = str(market).upper()
        with self.db.get_session() as session:
            rows = session.execute(
                select(MarketDataSymbol)
                .where(
                    MarketDataSymbol.market == normalized,
                    MarketDataSymbol.enabled.is_(True),
                    sync_column.is_(True),
                )
                .order_by(MarketDataSymbol.code)
            ).scalars().all()
            for row in rows:
                session.expunge(row)
            return list(rows)

    def upsert_symbols(self, symbols: Iterable[dict[str, Any]]) -> int:
        now = utc_now()
        records: list[dict[str, Any]] = []
        for item in symbols:
            market = str(item["market"]).upper()
            code = validate_market_data_code(market, item["code"])
            records.append(
                {
                    "market": market,
                    "code": code,
                    "name": str(item["name"]),
                    "enabled": bool(item.get("enabled", True)),
                    "sync_daily": bool(item.get("sync_daily", True)),
                    "sync_minute": bool(item.get("sync_minute", True)),
                    "lot_size": item.get("lot_size"),
                    "created_at": now,
                    "updated_at": now,
                }
            )
        if not records:
            return 0
        with self.db.session_scope() as session:
            stmt = pg_insert(MarketDataSymbol).values(records)
            session.execute(
                stmt.on_conflict_do_update(
                    constraint="uix_market_data_symbol_code",
                    set_={
                        "name": stmt.excluded.name,
                        "lot_size": func.coalesce(stmt.excluded.lot_size, MarketDataSymbol.lot_size),
                        "updated_at": stmt.excluded.updated_at,
                    },
                )
            )
        return len(records)


class StockRepository:
    """Raw-bar queries and priority-aware PostgreSQL batch UPSERTs."""

    def __init__(self, db_manager=None):
        if db_manager is None:
            from finance_analysis.database.session import DatabaseManager

            db_manager = DatabaseManager.get_instance()
        self.db = db_manager

    @staticmethod
    def _canonical_code(code: str) -> str:
        canonical = str(code or "").strip().upper()
        if canonical.endswith(".US"):
            market = "US"
        elif canonical.endswith(".HK"):
            market = "HK"
        elif canonical.endswith((".SH", ".SZ")):
            market = "CN"
        else:
            raise ValueError(f"Canonical ticker.region code required: {code!r}")
        return validate_market_data_code(market, canonical)

    def has_daily_data(self, symbol_id: int) -> bool:
        return self._exists(StockDaily, symbol_id)

    def has_minute_data(self, symbol_id: int) -> bool:
        return self._exists(StockMinute, symbol_id)

    def _exists(self, model, symbol_id: int) -> bool:
        with self.db.get_session() as session:
            return session.execute(
                select(model.id).where(model.symbol_id == symbol_id).limit(1)
            ).scalar_one_or_none() is not None

    def get_latest(self, code: str, days: int = 2, market: Optional[str] = None) -> list[StockDaily]:
        del market
        canonical = self._canonical_code(code)
        with self.db.get_session() as session:
            return list(
                session.execute(
                    select(StockDaily)
                    .join(MarketDataSymbol)
                    .where(MarketDataSymbol.code == canonical)
                    .order_by(desc(StockDaily.date))
                    .limit(days)
                ).scalars().unique().all()
            )

    def get_range(
        self,
        code: str,
        start_date: date,
        end_date: date,
        market: Optional[str] = None,
    ) -> list[StockDaily]:
        del market
        canonical = self._canonical_code(code)
        with self.db.get_session() as session:
            return list(
                session.execute(
                    select(StockDaily)
                    .join(MarketDataSymbol)
                    .where(
                        MarketDataSymbol.code == canonical,
                        StockDaily.date >= start_date,
                        StockDaily.date <= end_date,
                    )
                    .order_by(StockDaily.date)
                ).scalars().unique().all()
            )

    def get_with_warmup(self, code: str, start_date: date, end_date: date, warmup_days: int) -> list[StockDaily]:
        canonical = self._canonical_code(code)
        with self.db.get_session() as session:
            warmup = list(
                session.execute(
                    select(StockDaily)
                    .join(MarketDataSymbol)
                    .where(MarketDataSymbol.code == canonical, StockDaily.date < start_date)
                    .order_by(StockDaily.date.desc())
                    .limit(warmup_days)
                ).scalars().unique().all()
            )
            requested = list(
                session.execute(
                    select(StockDaily)
                    .join(MarketDataSymbol)
                    .where(
                        MarketDataSymbol.code == canonical,
                        StockDaily.date >= start_date,
                        StockDaily.date <= end_date,
                    )
                    .order_by(StockDaily.date)
                ).scalars().unique().all()
            )
            return list(reversed(warmup)) + requested

    def daily_coverage(self, symbol_id: int, start_date: date, end_date: date) -> dict[str, Any]:
        with self.db.get_session() as session:
            bounds = session.execute(
                select(func.min(StockDaily.date), func.max(StockDaily.date)).where(
                    StockDaily.symbol_id == symbol_id
                )
            ).one()
            row = session.execute(
                select(
                    func.count(StockDaily.id),
                    func.count(StockDaily.id).filter(StockDaily.open <= 0),
                ).where(
                    StockDaily.symbol_id == symbol_id,
                    StockDaily.date >= start_date,
                    StockDaily.date <= end_date,
                )
            ).one()
            return {
                "available_date_from": bounds[0],
                "available_date_to": bounds[1],
                "available_trading_days": int(row[0] or 0),
                "missing_open_days": int(row[1] or 0),
            }

    def get_minute_range(self, code: str, start_time: datetime, end_time: datetime) -> list[StockMinute]:
        canonical = self._canonical_code(code)
        with self.db.get_session() as session:
            return list(
                session.execute(
                    select(StockMinute)
                    .join(MarketDataSymbol)
                    .where(
                        MarketDataSymbol.code == canonical,
                        StockMinute.bar_time >= start_time,
                        StockMinute.bar_time < end_time,
                    )
                    .order_by(StockMinute.bar_time)
                ).scalars().unique().all()
            )

    def get_start_daily(
        self, *, code: str, analysis_date: date, market: Optional[str] = None
    ) -> Optional[StockDaily]:
        del market
        canonical = self._canonical_code(code)
        with self.db.get_session() as session:
            return session.execute(
                select(StockDaily)
                .join(MarketDataSymbol)
                .where(MarketDataSymbol.code == canonical, StockDaily.date <= analysis_date)
                .order_by(desc(StockDaily.date))
                .limit(1)
            ).scalars().unique().one_or_none()

    def get_forward_bars(
        self, *, code: str, analysis_date: date, eval_window_days: int, market: Optional[str] = None
    ) -> list[StockDaily]:
        del market
        canonical = self._canonical_code(code)
        with self.db.get_session() as session:
            return list(
                session.execute(
                    select(StockDaily)
                    .join(MarketDataSymbol)
                    .where(MarketDataSymbol.code == canonical, StockDaily.date > analysis_date)
                    .order_by(StockDaily.date)
                    .limit(eval_window_days)
                ).scalars().unique().all()
            )

    def latest_daily_date(self, symbol_id: int) -> Optional[date]:
        with self.db.get_session() as session:
            return session.execute(
                select(func.max(StockDaily.date)).where(StockDaily.symbol_id == symbol_id)
            ).scalar_one()

    def daily_dates(self, symbol_id: int, start_date: date, end_date: date) -> set[date]:
        with self.db.get_session() as session:
            return set(
                session.execute(
                    select(StockDaily.date).where(
                        StockDaily.symbol_id == symbol_id,
                        StockDaily.date >= start_date,
                        StockDaily.date <= end_date,
                    )
                ).scalars().all()
            )

    def minute_times(self, symbol_id: int, start_time: datetime, end_time: datetime) -> set[datetime]:
        with self.db.get_session() as session:
            return set(
                session.execute(
                    select(StockMinute.bar_time).where(
                        StockMinute.symbol_id == symbol_id,
                        StockMinute.bar_time >= start_time,
                        StockMinute.bar_time < end_time,
                    )
                ).scalars().all()
            )

    def upsert_daily(self, symbol_id: int, bars: Sequence[dict[str, Any]], source: str, priority: int) -> UpsertStats:
        records = self._daily_records(symbol_id, bars, source, priority)
        return self._upsert(
            StockDaily,
            records,
            "uix_stock_daily_symbol_date",
            (
                "open", "high", "low", "close", "volume", "amount", "limit_up", "limit_down", "suspended",
                "data_source", "source_priority", "updated_at",
            ),
        )

    def upsert_minute(self, symbol_id: int, bars: Sequence[dict[str, Any]], source: str, priority: int) -> UpsertStats:
        records = self._minute_records(symbol_id, bars, source, priority)
        return self._upsert(
            StockMinute,
            records,
            "uix_stock_minute_symbol_time",
            (
                "open", "high", "low", "close", "volume", "amount", "session_type",
                "data_source", "source_priority", "updated_at",
            ),
        )

    @staticmethod
    def _daily_records(
        symbol_id: int, bars: Sequence[dict[str, Any]], source: str, priority: int
    ) -> list[dict[str, Any]]:
        now = utc_now()
        return [
            {
                "symbol_id": symbol_id,
                "date": row["date"],
                "open": row["open"], "high": row["high"], "low": row["low"], "close": row["close"],
                "volume": row["volume"], "amount": row.get("amount"),
                "limit_up": row.get("limit_up"), "limit_down": row.get("limit_down"),
                "suspended": bool(row.get("suspended", False)),
                "data_source": source, "source_priority": priority,
                "created_at": now, "updated_at": now,
            }
            for row in bars
        ]

    @staticmethod
    def _minute_records(
        symbol_id: int, bars: Sequence[dict[str, Any]], source: str, priority: int
    ) -> list[dict[str, Any]]:
        now = utc_now()
        return [
            {
                "symbol_id": symbol_id,
                "bar_time": row["bar_time"].astimezone(timezone.utc),
                "open": row["open"], "high": row["high"], "low": row["low"], "close": row["close"],
                "volume": row["volume"], "amount": row.get("amount"), "session_type": "regular",
                "data_source": source, "source_priority": priority,
                "created_at": now, "updated_at": now,
            }
            for row in bars
        ]

    def _upsert(
        self, model, records: list[dict[str, Any]], constraint: str, update_columns: tuple[str, ...]
    ) -> UpsertStats:
        if not records:
            return UpsertStats()
        # PostgreSQL performs the priority comparison atomically in the conflict
        # UPDATE predicate. Lower-priority fallback bars may fill gaps but cannot
        # overwrite better data under concurrent workers.
        with self.db.session_scope() as session:
            stmt = pg_insert(model).values(records)
            result = session.execute(
                stmt.on_conflict_do_update(
                    constraint=constraint,
                    set_={column: getattr(stmt.excluded, column) for column in update_columns},
                    where=stmt.excluded.source_priority >= model.source_priority,
                ).returning(literal_column("(xmax = 0)").label("inserted"))
            )
            flags = [bool(row.inserted) for row in result]
        inserted = sum(flags)
        updated = len(flags) - inserted
        return UpsertStats(inserted, updated, len(records) - len(flags))


__all__ = ["MarketDataSymbolRepository", "StockRepository", "UpsertStats"]

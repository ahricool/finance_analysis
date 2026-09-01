# -*- coding: utf-8 -*-
"""Repositories for canonical symbols and historical market data."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import delete, desc, func, literal_column, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from finance_analysis.core.time import utc_now
from finance_analysis.database.models.stock import (
    MarketDataSymbol,
    StockDaily,
    StockMinute,
    validate_market_data_code,
)

_CJK_CHARACTER = r"\u3400-\u9fff"


def _normalize_security_name(value: str | None) -> str:
    """Normalize provider names without damaging meaningful English spaces."""
    name = " ".join(str(value or "").strip().split())
    if not name:
        return ""
    return re.sub(rf"(?<=[{_CJK_CHARACTER}])\s+(?=[{_CJK_CHARACTER}])", "", name)


@dataclass(frozen=True)
class UpsertStats:
    inserted_rows: int = 0
    updated_rows: int = 0
    deleted_rows: int = 0

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

    def names_by_codes(self, codes: Iterable[str]) -> dict[str, str]:
        """Return persisted names for canonical codes in one bounded query."""
        canonical_codes = sorted(
            {str(code or "").strip().upper() for code in codes if str(code or "").strip()}
        )
        if not canonical_codes:
            return {}
        with self.db.get_session() as session:
            rows = session.execute(
                select(MarketDataSymbol.code, MarketDataSymbol.name).where(
                    MarketDataSymbol.code.in_(canonical_codes)
                )
            ).all()
        return {
            str(code): normalized
            for code, name in rows
            if (normalized := _normalize_security_name(name))
        }

    def list_enabled_daily_symbols(self, market: str) -> list[MarketDataSymbol]:
        return self._list_enabled(market, MarketDataSymbol.sync_daily)

    def list_enabled_daily_by_codes(self, market: str, codes: Iterable[str]) -> list[MarketDataSymbol]:
        normalized = str(market).upper()
        canonical_codes = sorted({validate_market_data_code(normalized, code) for code in codes})
        if not canonical_codes:
            return []
        with self.db.get_session() as session:
            rows = session.execute(
                select(MarketDataSymbol)
                .where(
                    MarketDataSymbol.market == normalized,
                    MarketDataSymbol.code.in_(canonical_codes),
                    MarketDataSymbol.enabled.is_(True),
                    MarketDataSymbol.sync_daily.is_(True),
                )
                .order_by(MarketDataSymbol.code)
            ).scalars().all()
            for row in rows:
                session.expunge(row)
            return list(rows)

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

    def upsert_symbols(
        self,
        symbols: Iterable[dict[str, Any]],
        *,
        overwrite_runtime_flags: bool = False,
        force_daily_sync: bool = False,
    ) -> int:
        now = utc_now()
        records = self._normalize_upsert_records(symbols, now)
        if not records:
            return 0
        with self.db.session_scope() as session:
            stmt = pg_insert(MarketDataSymbol).values(records)
            update_values = {
                "name": stmt.excluded.name,
                "updated_at": stmt.excluded.updated_at,
            }
            if overwrite_runtime_flags:
                update_values.update(
                    {
                        "enabled": stmt.excluded.enabled,
                        "sync_daily": stmt.excluded.sync_daily,
                        "sync_minute": stmt.excluded.sync_minute,
                    }
                )
            elif force_daily_sync:
                # Strategy dependencies may require daily data without taking
                # ownership of a watched symbol's minute-sync preference.
                update_values.update(
                    {
                        "enabled": stmt.excluded.enabled,
                        "sync_daily": stmt.excluded.sync_daily,
                    }
                )
            session.execute(
                stmt.on_conflict_do_update(
                    constraint="uix_market_data_symbol_code",
                    set_=update_values,
                )
            )
        return len(records)

    @staticmethod
    def _normalize_upsert_records(
        symbols: Iterable[dict[str, Any]],
        now: datetime,
    ) -> list[dict[str, Any]]:
        records_by_code: dict[str, dict[str, Any]] = {}
        for item in symbols:
            market = str(item["market"]).upper()
            code = validate_market_data_code(market, item["code"])
            records_by_code[code] = {
                "market": market,
                "code": code,
                "name": _normalize_security_name(item["name"]),
                "enabled": bool(item.get("enabled", True)),
                "sync_daily": bool(item.get("sync_daily", True)),
                "sync_minute": bool(item.get("sync_minute", True)),
                "created_at": now,
                "updated_at": now,
            }
        return list(records_by_code.values())


class StockRepository:
    """Provider bar queries and deterministic PostgreSQL batch UPSERTs."""

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

    def daily_closes(self, symbol_id: int, start_date: date, end_date: date) -> dict[date, float]:
        """Return stored closes for overlap checks during incremental synchronization."""
        with self.db.get_session() as session:
            rows = session.execute(
                select(StockDaily.date, StockDaily.close).where(
                    StockDaily.symbol_id == symbol_id,
                    StockDaily.date >= start_date,
                    StockDaily.date <= end_date,
                )
            ).all()
        return {trade_date: float(close) for trade_date, close in rows if close is not None}

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

    def upsert_daily(self, symbol_id: int, bars: Sequence[dict[str, Any]], source: str) -> UpsertStats:
        records = self._daily_records(symbol_id, bars, source)
        return self._upsert(
            StockDaily,
            records,
            "uix_stock_daily_symbol_date",
            (
                "open", "high", "low", "close", "volume", "amount", "data_source", "updated_at",
            ),
        )

    def replace_daily_history(self, symbol_id: int, bars: Sequence[dict[str, Any]], source: str) -> UpsertStats:
        """Atomically replace all daily history for one symbol with fetched bars."""
        records = self._daily_records(symbol_id, bars, source)
        if not records:
            raise ValueError("Refusing to replace daily history with an empty fetch result")
        with self.db.session_scope() as session:
            deleted = session.execute(
                delete(StockDaily).where(StockDaily.symbol_id == symbol_id)
            )
            session.execute(StockDaily.__table__.insert(), records)
            deleted_rows = int(deleted.rowcount or 0)
        return UpsertStats(inserted_rows=len(records), deleted_rows=deleted_rows)

    def upsert_minute(self, symbol_id: int, bars: Sequence[dict[str, Any]], source: str) -> UpsertStats:
        records = self._minute_records(symbol_id, bars, source)
        return self._upsert(
            StockMinute,
            records,
            "uix_stock_minute_symbol_time",
            (
                "open", "high", "low", "close", "volume", "amount", "session_type",
                "data_source", "updated_at",
            ),
        )

    @staticmethod
    def _daily_records(
        symbol_id: int, bars: Sequence[dict[str, Any]], source: str
    ) -> list[dict[str, Any]]:
        now = utc_now()
        return [
            {
                "symbol_id": symbol_id,
                "date": row["date"],
                "open": row["open"], "high": row["high"], "low": row["low"], "close": row["close"],
                "volume": row["volume"], "amount": row.get("amount"),
                "data_source": source,
                "created_at": now, "updated_at": now,
            }
            for row in bars
        ]

    def delete_daily_before(self, symbol_id: int, cutoff_date: date) -> int:
        """Delete expired daily bars for one symbol."""
        with self.db.session_scope() as session:
            result = session.execute(
                delete(StockDaily).where(
                    StockDaily.symbol_id == symbol_id,
                    StockDaily.date < cutoff_date,
                )
            )
            return int(result.rowcount or 0)

    def delete_daily_before_symbols(self, symbol_ids: Sequence[int], cutoff_date: date) -> int:
        """Delete expired daily bars for the task scope before synchronization."""
        ids = list(symbol_ids)
        if not ids:
            return 0
        with self.db.session_scope() as session:
            result = session.execute(
                delete(StockDaily).where(
                    StockDaily.symbol_id.in_(ids),
                    StockDaily.date < cutoff_date,
                )
            )
            return int(result.rowcount or 0)

    @staticmethod
    def _minute_records(
        symbol_id: int, bars: Sequence[dict[str, Any]], source: str
    ) -> list[dict[str, Any]]:
        now = utc_now()
        return [
            {
                "symbol_id": symbol_id,
                "bar_time": row["bar_time"].astimezone(timezone.utc),
                "open": row["open"], "high": row["high"], "low": row["low"], "close": row["close"],
                "volume": row["volume"], "amount": row.get("amount"), "session_type": "regular",
                "data_source": source,
                "created_at": now, "updated_at": now,
            }
            for row in bars
        ]

    def _upsert(
        self, model, records: list[dict[str, Any]], constraint: str, update_columns: tuple[str, ...]
    ) -> UpsertStats:
        if not records:
            return UpsertStats()
        with self.db.session_scope() as session:
            stmt = pg_insert(model).values(records)
            result = session.execute(
                stmt.on_conflict_do_update(
                    constraint=constraint,
                    set_={column: getattr(stmt.excluded, column) for column in update_columns},
                ).returning(literal_column("(xmax = 0)").label("inserted"))
            )
            flags = [bool(row.inserted) for row in result]
        inserted = sum(flags)
        updated = len(flags) - inserted
        return UpsertStats(inserted, updated)


__all__ = ["MarketDataSymbolRepository", "StockRepository", "UpsertStats"]

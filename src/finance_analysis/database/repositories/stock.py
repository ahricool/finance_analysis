# -*- coding: utf-8 -*-
"""Repositories for canonical symbols and historical market data."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable, Optional, Sequence

from sqlalchemy import and_, case, delete, desc, func, literal_column, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from finance_analysis.core.time import utc_now
from finance_analysis.database.models.stock import (
    Instrument,
    StockDaily,
    validate_instrument_code,
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


class InstrumentRepository:
    def __init__(self, db_manager=None):
        if db_manager is None:
            from finance_analysis.database.session import DatabaseManager

            db_manager = DatabaseManager.get_instance()
        self.db = db_manager

    def get_by_code(self, code: str) -> Optional[Instrument]:
        canonical = str(code or "").strip().upper()
        with self.db.get_session() as session:
            row = session.execute(select(Instrument).where(Instrument.code == canonical)).scalar_one_or_none()
            if row is not None:
                session.expunge(row)
            return row

    def names_by_codes(self, codes: Iterable[str]) -> dict[str, str]:
        """Return persisted names for canonical codes in one bounded query."""
        canonical_codes = sorted({str(code or "").strip().upper() for code in codes if str(code or "").strip()})
        if not canonical_codes:
            return {}
        with self.db.get_session() as session:
            rows = session.execute(
                select(Instrument.code, Instrument.name).where(Instrument.code.in_(canonical_codes))
            ).all()
        return {str(code): normalized for code, name in rows if (normalized := _normalize_security_name(name))}

    def list_enabled_daily_symbols(self, market: str) -> list[Instrument]:
        return self.list_enabled_symbols(market)

    def list_enabled_daily_by_codes(self, market: str, codes: Iterable[str]) -> list[Instrument]:
        normalized = str(market).upper()
        canonical_codes = sorted({validate_instrument_code(normalized, code) for code in codes})
        if not canonical_codes:
            return []
        with self.db.get_session() as session:
            rows = (
                session.execute(
                    select(Instrument)
                    .where(
                        Instrument.market == normalized,
                        Instrument.code.in_(canonical_codes),
                        Instrument.listing_status == "ACTIVE",
                    )
                    .order_by(Instrument.code)
                )
                .scalars()
                .all()
            )
            for row in rows:
                session.expunge(row)
            return list(rows)

    def list_enabled_symbols(self, market: str) -> list[Instrument]:
        normalized = str(market).upper()
        with self.db.get_session() as session:
            rows = (
                session.execute(
                    select(Instrument)
                    .where(Instrument.market == normalized, Instrument.listing_status == "ACTIVE")
                    .order_by(Instrument.code)
                )
                .scalars()
                .all()
            )
            for row in rows:
                session.expunge(row)
            return list(rows)

    def search_enabled_symbols(self, market: str, keyword: str = "", limit: int = 20) -> list[Instrument]:
        normalized = str(market).upper()
        needle = str(keyword or "").strip()
        with self.db.get_session() as session:
            query = select(Instrument).where(
                Instrument.market == normalized,
                Instrument.listing_status == "ACTIVE",
            )
            if needle:
                pattern = f"%{needle}%"
                query = query.where(or_(Instrument.code.ilike(pattern), Instrument.name.ilike(pattern)))
            rows = session.execute(query.order_by(Instrument.code).limit(limit)).scalars().all()
            for row in rows:
                session.expunge(row)
            return list(rows)

    def upsert_symbols(self, symbols: Iterable[dict[str, Any]]) -> int:
        now = utc_now()
        records = self._normalize_upsert_records(symbols, now)
        if not records:
            return 0
        with self.db.session_scope() as session:
            sqlite = session.bind.dialect.name == "sqlite"
            grouped: dict[frozenset[str], list[dict[str, Any]]] = {}
            for values, explicit_fields in records:
                grouped.setdefault(explicit_fields, []).append(values)
            for explicit_fields, values in grouped.items():
                stmt = (sqlite_insert if sqlite else pg_insert)(Instrument).values(values)
                update_values = {"updated_at": stmt.excluded.updated_at}
                for field in explicit_fields:
                    column_name = "metadata" if field == "instrument_metadata" else field
                    excluded = getattr(stmt.excluded, column_name)
                    if field == "source":
                        excluded = case(
                            (
                                and_(Instrument.source == "TICKFLOW", stmt.excluded.source == "AKSHARE"),
                                Instrument.source,
                            ),
                            else_=stmt.excluded.source,
                        )
                    update_values[column_name] = excluded
                conflict = (
                    {"index_elements": [Instrument.code]}
                    if sqlite
                    else {"constraint": "uix_instrument_code"}
                )
                session.execute(stmt.on_conflict_do_update(**conflict, set_=update_values))
        return len(records)

    def mark_missing_delisted(self, market: str, active_codes: Iterable[str]) -> int:
        """Mark missing listings only after a complete primary-provider directory fetch."""
        normalized = str(market).strip().upper()
        codes = {validate_instrument_code(normalized, code) for code in active_codes}
        if not codes:
            raise ValueError("A complete instrument directory must not be empty")
        with self.db.session_scope() as session:
            result = session.execute(
                update(Instrument)
                .where(
                    Instrument.market == normalized,
                    Instrument.listing_status == "ACTIVE",
                    Instrument.code.not_in(codes),
                )
                .values(listing_status="DELISTED", updated_at=utc_now())
            )
            return int(result.rowcount or 0)

    @staticmethod
    def _normalize_upsert_records(
        symbols: Iterable[dict[str, Any]],
        now: datetime,
    ) -> list[tuple[dict[str, Any], frozenset[str]]]:
        records_by_code: dict[str, tuple[dict[str, Any], frozenset[str]]] = {}
        for item in symbols:
            market = str(item["market"]).upper()
            code = validate_instrument_code(market, item["code"])
            values = {
                "market": market,
                "code": code,
                "native_code": str(item.get("native_code") or code.rsplit(".", 1)[0]),
                "name": _normalize_security_name(item.get("name")) or code,
                "instrument_type": str(item.get("instrument_type") or "STOCK").upper(),
                "currency": str(item.get("currency") or {"CN": "CNY", "US": "USD", "HK": "HKD"}[market]),
                "listing_date": item.get("listing_date"),
                "listing_status": str(item.get("listing_status") or "ACTIVE").upper(),
                "source": str(item.get("source") or "MANUAL").upper(),
                "instrument_metadata": item.get("metadata", {}),
                "created_at": now,
                "updated_at": now,
            }
            explicit_fields = {
                field
                for field in (
                    "native_code",
                    "name",
                    "instrument_type",
                    "currency",
                    "listing_date",
                    "listing_status",
                    "source",
                )
                if field in item and item[field] is not None
            }
            if item.get("metadata"):
                explicit_fields.add("instrument_metadata")
            records_by_code[code] = (values, frozenset(explicit_fields))
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
        elif canonical.endswith((".SH", ".SZ", ".BJ")):
            market = "CN"
        else:
            raise ValueError(f"Canonical ticker.region code required: {code!r}")
        return validate_instrument_code(market, canonical)

    def has_daily_data(self, instrument_id: int) -> bool:
        return self._exists(StockDaily, instrument_id)

    def _exists(self, model, instrument_id: int) -> bool:
        with self.db.get_session() as session:
            return (
                session.execute(
                    select(model.id).where(model.instrument_id == instrument_id).limit(1)
                ).scalar_one_or_none()
                is not None
            )

    def get_latest(self, code: str, days: int = 2, market: Optional[str] = None) -> list[StockDaily]:
        del market
        canonical = self._canonical_code(code)
        with self.db.get_session() as session:
            return list(
                session.execute(
                    select(StockDaily)
                    .join(Instrument)
                    .where(Instrument.code == canonical)
                    .order_by(desc(StockDaily.date))
                    .limit(days)
                )
                .scalars()
                .unique()
                .all()
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
                    .join(Instrument)
                    .where(
                        Instrument.code == canonical,
                        StockDaily.date >= start_date,
                        StockDaily.date <= end_date,
                    )
                    .order_by(StockDaily.date)
                )
                .scalars()
                .unique()
                .all()
            )

    def get_with_warmup(self, code: str, start_date: date, end_date: date, warmup_days: int) -> list[StockDaily]:
        canonical = self._canonical_code(code)
        with self.db.get_session() as session:
            warmup = list(
                session.execute(
                    select(StockDaily)
                    .join(Instrument)
                    .where(Instrument.code == canonical, StockDaily.date < start_date)
                    .order_by(StockDaily.date.desc())
                    .limit(warmup_days)
                )
                .scalars()
                .unique()
                .all()
            )
            requested = list(
                session.execute(
                    select(StockDaily)
                    .join(Instrument)
                    .where(
                        Instrument.code == canonical,
                        StockDaily.date >= start_date,
                        StockDaily.date <= end_date,
                    )
                    .order_by(StockDaily.date)
                )
                .scalars()
                .unique()
                .all()
            )
            return list(reversed(warmup)) + requested

    def daily_coverage(self, instrument_id: int, start_date: date, end_date: date) -> dict[str, Any]:
        with self.db.get_session() as session:
            bounds = session.execute(
                select(func.min(StockDaily.date), func.max(StockDaily.date)).where(
                    StockDaily.instrument_id == instrument_id
                )
            ).one()
            row = session.execute(
                select(
                    func.count(StockDaily.id),
                    func.count(StockDaily.id).filter(StockDaily.open <= 0),
                ).where(
                    StockDaily.instrument_id == instrument_id,
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

    def get_start_daily(self, *, code: str, analysis_date: date, market: Optional[str] = None) -> Optional[StockDaily]:
        del market
        canonical = self._canonical_code(code)
        with self.db.get_session() as session:
            return (
                session.execute(
                    select(StockDaily)
                    .join(Instrument)
                    .where(Instrument.code == canonical, StockDaily.date <= analysis_date)
                    .order_by(desc(StockDaily.date))
                    .limit(1)
                )
                .scalars()
                .unique()
                .one_or_none()
            )

    def get_forward_bars(
        self, *, code: str, analysis_date: date, eval_window_days: int, market: Optional[str] = None
    ) -> list[StockDaily]:
        del market
        canonical = self._canonical_code(code)
        with self.db.get_session() as session:
            return list(
                session.execute(
                    select(StockDaily)
                    .join(Instrument)
                    .where(Instrument.code == canonical, StockDaily.date > analysis_date)
                    .order_by(StockDaily.date)
                    .limit(eval_window_days)
                )
                .scalars()
                .unique()
                .all()
            )

    def latest_daily_date(self, instrument_id: int) -> Optional[date]:
        with self.db.get_session() as session:
            return session.execute(
                select(func.max(StockDaily.date)).where(StockDaily.instrument_id == instrument_id)
            ).scalar_one()

    def daily_dates(self, instrument_id: int, start_date: date, end_date: date) -> set[date]:
        with self.db.get_session() as session:
            return set(
                session.execute(
                    select(StockDaily.date).where(
                        StockDaily.instrument_id == instrument_id,
                        StockDaily.date >= start_date,
                        StockDaily.date <= end_date,
                    )
                )
                .scalars()
                .all()
            )

    def daily_closes(self, instrument_id: int, start_date: date, end_date: date) -> dict[date, float]:
        """Return stored closes for overlap checks during incremental synchronization."""
        with self.db.get_session() as session:
            rows = session.execute(
                select(StockDaily.date, StockDaily.close).where(
                    StockDaily.instrument_id == instrument_id,
                    StockDaily.date >= start_date,
                    StockDaily.date <= end_date,
                )
            ).all()
        return {trade_date: float(close) for trade_date, close in rows if close is not None}

    def upsert_daily(self, instrument_id: int, bars: Sequence[dict[str, Any]], source: str) -> UpsertStats:
        records = self._daily_records(instrument_id, bars, source)
        return self._upsert(
            StockDaily,
            records,
            "uix_stock_daily_instrument_date",
            (
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
                "data_source",
                "updated_at",
            ),
        )

    def replace_daily_history(self, instrument_id: int, bars: Sequence[dict[str, Any]], source: str) -> UpsertStats:
        """Atomically replace all daily history for one symbol with fetched bars."""
        records = self._daily_records(instrument_id, bars, source)
        if not records:
            raise ValueError("Refusing to replace daily history with an empty fetch result")
        with self.db.session_scope() as session:
            deleted = session.execute(delete(StockDaily).where(StockDaily.instrument_id == instrument_id))
            session.execute(StockDaily.__table__.insert(), records)
            deleted_rows = int(deleted.rowcount or 0)
        return UpsertStats(inserted_rows=len(records), deleted_rows=deleted_rows)

    @staticmethod
    def _daily_records(instrument_id: int, bars: Sequence[dict[str, Any]], source: str) -> list[dict[str, Any]]:
        now = utc_now()
        return [
            {
                "instrument_id": instrument_id,
                "date": row["date"],
                "open": row["open"],
                "high": row["high"],
                "low": row["low"],
                "close": row["close"],
                "volume": row["volume"],
                "amount": row.get("amount"),
                "data_source": row.get("data_source", source),
                "created_at": now,
                "updated_at": now,
            }
            for row in bars
        ]

    def delete_daily_before(self, instrument_id: int, cutoff_date: date) -> int:
        """Delete expired daily bars for one symbol."""
        with self.db.session_scope() as session:
            result = session.execute(
                delete(StockDaily).where(
                    StockDaily.instrument_id == instrument_id,
                    StockDaily.date < cutoff_date,
                )
            )
            return int(result.rowcount or 0)

    def delete_daily_before_symbols(self, instrument_ids: Sequence[int], cutoff_date: date) -> int:
        """Delete expired daily bars for the task scope before synchronization."""
        ids = list(instrument_ids)
        if not ids:
            return 0
        with self.db.session_scope() as session:
            result = session.execute(
                delete(StockDaily).where(
                    StockDaily.instrument_id.in_(ids),
                    StockDaily.date < cutoff_date,
                )
            )
            return int(result.rowcount or 0)

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


__all__ = ["InstrumentRepository", "StockRepository", "UpsertStats"]

"""Repositories for corporate actions and daily price adjustment factors."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date
from typing import Any, Sequence

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from finance_analysis.core.time import utc_now
from finance_analysis.database.models.stock import StockAdjustmentFactor, StockCorporateAction


def stable_row_hash(row: dict[str, Any], *, ignored: Sequence[str] = ()) -> str:
    payload = {key: value for key, value in row.items() if key not in ignored}
    encoded = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class AdjustmentWriteStats:
    changed: bool = False
    inserted_rows: int = 0
    updated_rows: int = 0
    deleted_rows: int = 0


class StockAdjustmentRepository:
    """Replace one symbol's correction window only when provider data changed."""

    def __init__(self, db_manager=None):
        if db_manager is None:
            from finance_analysis.database.session import DatabaseManager

            db_manager = DatabaseManager.get_instance()
        self.db = db_manager

    def replace_corporate_actions(
        self,
        symbol_id: int,
        start_date: date,
        end_date: date,
        rows: Sequence[dict[str, Any]],
        source: str,
    ) -> AdjustmentWriteStats:
        return self._replace_window(
            StockCorporateAction,
            symbol_id,
            "action_date",
            ("action_date", "action_type"),
            start_date,
            end_date,
            rows,
            source,
        )

    def replace_adjustment_factors(
        self,
        symbol_id: int,
        start_date: date,
        end_date: date,
        rows: Sequence[dict[str, Any]],
        source: str,
    ) -> AdjustmentWriteStats:
        return self._replace_window(
            StockAdjustmentFactor,
            symbol_id,
            "trade_date",
            ("trade_date",),
            start_date,
            end_date,
            rows,
            source,
        )

    def upsert_corporate_actions(
        self,
        symbol_id: int,
        start_date: date,
        end_date: date,
        rows: Sequence[dict[str, Any]],
        source: str,
    ) -> AdjustmentWriteStats:
        return self._upsert_window(
            StockCorporateAction,
            symbol_id,
            "action_date",
            ("action_date", "action_type"),
            "uix_stock_corporate_action_symbol_date_type",
            start_date,
            end_date,
            rows,
            source,
        )

    def upsert_adjustment_factors(
        self,
        symbol_id: int,
        start_date: date,
        end_date: date,
        rows: Sequence[dict[str, Any]],
        source: str,
    ) -> AdjustmentWriteStats:
        return self._upsert_window(
            StockAdjustmentFactor,
            symbol_id,
            "trade_date",
            ("trade_date",),
            "uix_stock_adjustment_factor_symbol_date",
            start_date,
            end_date,
            rows,
            source,
        )

    def has_corporate_action_changes(
        self,
        symbol_id: int,
        start_date: date,
        end_date: date,
        rows: Sequence[dict[str, Any]],
        source: str,
        *,
        complete: bool = False,
    ) -> bool:
        normalized = self._normalize_rows(
            rows,
            symbol_id=symbol_id,
            date_column_name="action_date",
            start_date=start_date,
            end_date=end_date,
            source=source,
        )
        if not normalized and not complete:
            return False
        incoming = {(row["action_date"], row["action_type"]): row["source_hash"] for row in normalized}
        with self.db.get_session() as session:
            existing = list(
                session.execute(
                    select(StockCorporateAction).where(
                        StockCorporateAction.symbol_id == symbol_id,
                        StockCorporateAction.action_date >= start_date,
                        StockCorporateAction.action_date <= end_date,
                    )
                ).scalars()
            )
        stored = {(row.action_date, row.action_type): row.source_hash for row in existing}
        if complete:
            return stored != incoming
        return any(stored.get(key) != value for key, value in incoming.items())

    def has_adjustment_factor_changes(
        self,
        symbol_id: int,
        start_date: date,
        end_date: date,
        rows: Sequence[dict[str, Any]],
    ) -> bool:
        """Compare only dates present in both the incoming and stored factor windows."""
        factor_columns = ("forward_adjustment_factor", "hfq_factor", "hfq_cash", "adj_close")
        incoming = {
            row["trade_date"]: tuple(row.get(column) for column in factor_columns)
            for row in rows
            if start_date <= row["trade_date"] <= end_date
        }
        if not incoming:
            return False
        with self.db.get_session() as session:
            existing = list(
                session.execute(
                    select(StockAdjustmentFactor).where(
                        StockAdjustmentFactor.symbol_id == symbol_id,
                        StockAdjustmentFactor.trade_date >= start_date,
                        StockAdjustmentFactor.trade_date <= end_date,
                    )
                ).scalars()
            )
        stored = {
            row.trade_date: tuple(getattr(row, column) for column in factor_columns)
            for row in existing
        }
        return any(stored[trade_date] != values for trade_date, values in incoming.items() if trade_date in stored)

    def delete_before(self, symbol_id: int, cutoff_date: date) -> int:
        """Prune expired adjustment metadata for one symbol."""
        with self.db.session_scope() as session:
            factors = session.execute(
                delete(StockAdjustmentFactor).where(
                    StockAdjustmentFactor.symbol_id == symbol_id,
                    StockAdjustmentFactor.trade_date < cutoff_date,
                )
            )
            actions = session.execute(
                delete(StockCorporateAction).where(
                    StockCorporateAction.symbol_id == symbol_id,
                    StockCorporateAction.action_date < cutoff_date,
                )
            )
            return int(factors.rowcount or 0) + int(actions.rowcount or 0)

    def delete_before_symbols(self, symbol_ids: Sequence[int], cutoff_date: date) -> int:
        """Prune expired adjustment metadata for the task scope before synchronization."""
        ids = list(symbol_ids)
        if not ids:
            return 0
        with self.db.session_scope() as session:
            factors = session.execute(
                delete(StockAdjustmentFactor).where(
                    StockAdjustmentFactor.symbol_id.in_(ids),
                    StockAdjustmentFactor.trade_date < cutoff_date,
                )
            )
            actions = session.execute(
                delete(StockCorporateAction).where(
                    StockCorporateAction.symbol_id.in_(ids),
                    StockCorporateAction.action_date < cutoff_date,
                )
            )
            return int(factors.rowcount or 0) + int(actions.rowcount or 0)

    def _replace_window(
        self,
        model,
        symbol_id: int,
        date_column_name: str,
        key_columns: tuple[str, ...],
        start_date: date,
        end_date: date,
        rows: Sequence[dict[str, Any]],
        source: str,
    ) -> AdjustmentWriteStats:
        date_column = getattr(model, date_column_name)
        normalized = self._normalize_rows(
            rows,
            symbol_id=symbol_id,
            date_column_name=date_column_name,
            start_date=start_date,
            end_date=end_date,
            source=source,
        )

        def key(item: Any) -> tuple[Any, ...]:
            if isinstance(item, dict):
                return tuple(item[column] for column in key_columns)
            return tuple(getattr(item, column) for column in key_columns)

        with self.db.session_scope() as session:
            existing = list(
                session.execute(
                    select(model).where(
                        model.symbol_id == symbol_id,
                        date_column >= start_date,
                        date_column <= end_date,
                    )
                ).scalars()
            )
            old_hashes = {key(item): item.source_hash for item in existing}
            new_hashes = {key(item): item["source_hash"] for item in normalized}
            if old_hashes == new_hashes:
                return AdjustmentWriteStats()

            session.execute(
                delete(model).where(
                    model.symbol_id == symbol_id,
                    date_column >= start_date,
                    date_column <= end_date,
                )
            )
            if normalized:
                session.execute(pg_insert(model).values(normalized))

        old_keys = set(old_hashes)
        new_keys = set(new_hashes)
        updated = sum(old_hashes[item] != new_hashes[item] for item in old_keys & new_keys)
        return AdjustmentWriteStats(
            changed=True,
            inserted_rows=len(new_keys - old_keys),
            updated_rows=updated,
            deleted_rows=len(old_keys - new_keys),
        )

    def _upsert_window(
        self,
        model,
        symbol_id: int,
        date_column_name: str,
        key_columns: tuple[str, ...],
        constraint: str,
        start_date: date,
        end_date: date,
        rows: Sequence[dict[str, Any]],
        source: str,
    ) -> AdjustmentWriteStats:
        normalized = self._normalize_rows(
            rows,
            symbol_id=symbol_id,
            date_column_name=date_column_name,
            start_date=start_date,
            end_date=end_date,
            source=source,
        )
        if not normalized:
            return AdjustmentWriteStats()

        def key(item: Any) -> tuple[Any, ...]:
            if isinstance(item, dict):
                return tuple(item[column] for column in key_columns)
            return tuple(getattr(item, column) for column in key_columns)

        date_column = getattr(model, date_column_name)
        with self.db.session_scope() as session:
            existing = list(
                session.execute(
                    select(model).where(
                        model.symbol_id == symbol_id,
                        date_column >= start_date,
                        date_column <= end_date,
                    )
                ).scalars()
            )
            old_hashes = {key(item): item.source_hash for item in existing}
            changed_rows = [row for row in normalized if old_hashes.get(key(row)) != row["source_hash"]]
            if not changed_rows:
                return AdjustmentWriteStats()
            stmt = pg_insert(model).values(changed_rows)
            excluded_keys = {"symbol_id", "created_at", *key_columns}
            update_columns = [column for column in changed_rows[0] if column not in excluded_keys]
            session.execute(
                stmt.on_conflict_do_update(
                    constraint=constraint,
                    set_={column: getattr(stmt.excluded, column) for column in update_columns},
                )
            )
        inserted = sum(key(row) not in old_hashes for row in changed_rows)
        return AdjustmentWriteStats(
            changed=True,
            inserted_rows=inserted,
            updated_rows=len(changed_rows) - inserted,
        )

    @staticmethod
    def _normalize_rows(
        rows: Sequence[dict[str, Any]],
        *,
        symbol_id: int,
        date_column_name: str,
        start_date: date,
        end_date: date,
        source: str,
    ) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        now = utc_now()
        for raw in rows:
            row = dict(raw)
            if not (start_date <= row[date_column_name] <= end_date):
                continue
            row["symbol_id"] = symbol_id
            row["data_source"] = source
            row["source_hash"] = row.get("source_hash") or stable_row_hash(
                row, ignored=("symbol_id", "data_source", "source_hash")
            )
            row["created_at"] = now
            row["updated_at"] = now
            normalized.append(row)
        return normalized


__all__ = ["AdjustmentWriteStats", "StockAdjustmentRepository", "stable_row_hash"]

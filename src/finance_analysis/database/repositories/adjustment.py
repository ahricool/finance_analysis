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


__all__ = ["AdjustmentWriteStats", "StockAdjustmentRepository", "stable_row_hash"]

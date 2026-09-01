"""Load canonical forward-adjusted daily bars from ``stock_daily``."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

DAILY_COLUMNS = (
    "instrument",
    "datetime",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "daily_data_source",
)


@dataclass(frozen=True)
class DailyBarLoadResult:
    frame: pd.DataFrame
    source_revision: str
    vwap: dict[str, int | float]


class DailyBarLoader:
    """Read already-adjusted daily prices without applying a second adjustment."""

    def __init__(self, repository: Any):
        self.repository = repository

    def load(
        self,
        market: str,
        codes: set[str],
        start: date,
        end: date,
    ) -> DailyBarLoadResult:
        rows = self.repository.load_daily_bar_rows(market.upper(), codes, start, end)
        frame = pd.DataFrame(rows, columns=DAILY_COLUMNS)
        if not frame.empty:
            frame = frame.sort_values(["instrument", "datetime"], kind="stable").reset_index(drop=True)
        frame, vwap_report = self._with_vwap(frame)
        revision = self._source_revision(frame)
        return DailyBarLoadResult(frame, revision, vwap_report)

    @staticmethod
    def _with_vwap(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int | float]]:
        result = frame.copy()
        total = len(result)
        if result.empty:
            return result, DailyBarLoader._vwap_report(0, 0, 0)
        low = pd.to_numeric(result["low"], errors="coerce")
        high = pd.to_numeric(result["high"], errors="coerce")
        close = pd.to_numeric(result["close"], errors="coerce")
        typical = (high + low + close) / 3.0
        result["vwap"] = typical
        result["vwap"] = result["vwap"].where(np.isfinite(result["vwap"]) & (result["vwap"] > 0))
        valid = result["vwap"].notna()
        return result, DailyBarLoader._vwap_report(
            total,
            int(valid.sum()),
            int((~valid).sum()),
        )

    @staticmethod
    def _vwap_report(total: int, estimated_rows: int, missing_rows: int) -> dict[str, int | float]:
        def ratio(value: int) -> float:
            return value / total if total else 0.0

        return {
            "valid_rows": estimated_rows,
            "estimated_rows": estimated_rows,
            "missing_rows": missing_rows,
            "estimated_ratio": ratio(estimated_rows),
            "missing_ratio": ratio(missing_rows),
        }

    @staticmethod
    def _source_revision(frame: pd.DataFrame) -> str:
        columns = [
            "instrument",
            "datetime",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "vwap",
            "daily_data_source",
        ]
        stable = frame.reindex(columns=columns).copy()
        if not stable.empty:
            stable["datetime"] = pd.to_datetime(stable["datetime"]).dt.strftime("%Y-%m-%d")
        payload = stable.to_csv(index=False, lineterminator="\n", na_rep="<null>", float_format="%.17g")
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = ["DailyBarLoadResult", "DailyBarLoader"]

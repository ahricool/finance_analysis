"""Load raw or forward-adjusted daily bars without duplicated adjustment logic."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from typing import Any

import numpy as np
import pandas as pd

from finance_analysis.quant.exceptions import AdjustmentFactorMissingError
from finance_analysis.quant.price_modes import PriceMode, normalize_price_mode

PRICE_COLUMNS = ("open", "high", "low", "close", "vwap")
RAW_COLUMNS = (
    "instrument",
    "datetime",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "vwap",
    "vwap_source",
    "vwap_quality",
    "daily_data_source",
    "daily_source_priority",
    "forward_adjustment_factor",
    "adjustment_source",
    "adjustment_source_hash",
)


@dataclass(frozen=True)
class DailyBarLoadResult:
    frame: pd.DataFrame
    source_revision: str
    adjustment_coverage: dict[str, Any]
    adjustment_sources: list[str]
    vwap: dict[str, int | float]
    price_mode: PriceMode


class DailyBarLoader:
    """Canonical adjustment boundary for all quantitative daily-price consumers.

    Price fields are multiplied exactly once. Volume and amount deliberately
    remain raw because the project has no independently sourced volume factor.
    """

    def __init__(self, repository: Any):
        self.repository = repository

    def load(
        self,
        market: str,
        codes: set[str],
        start: date,
        end: date,
        price_mode: str | PriceMode,
    ) -> DailyBarLoadResult:
        mode = normalize_price_mode(price_mode)
        rows = self.repository.load_daily_bar_rows(market.upper(), codes, start, end)
        frame = pd.DataFrame(rows, columns=RAW_COLUMNS)
        if not frame.empty:
            frame = frame.sort_values(["instrument", "datetime"], kind="stable").reset_index(drop=True)
        frame, vwap_report = self._with_raw_vwap(frame)
        coverage, sources = self._adjustment_coverage(frame)
        revision = self._source_revision(frame)
        if mode is PriceMode.FORWARD_ADJUSTED:
            self._require_complete_adjustments(frame, market.upper())
            frame = self._apply_forward_adjustment(frame)
        return DailyBarLoadResult(frame, revision, coverage, sources, vwap_report, mode)

    @staticmethod
    def _with_raw_vwap(frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, int | float]]:
        result = frame.copy()
        total = len(result)
        if result.empty:
            return result, DailyBarLoader._vwap_report(0, 0, 0, 0)
        low = pd.to_numeric(result["low"], errors="coerce")
        high = pd.to_numeric(result["high"], errors="coerce")
        close = pd.to_numeric(result["close"], errors="coerce")
        stored = pd.to_numeric(result["vwap"], errors="coerce")
        stored = stored.where(np.isfinite(stored) & (stored > 0))
        quality = result["vwap_quality"].fillna("").astype(str)
        typical = (high + low + close) / 3.0
        fallback = stored.isna() & np.isfinite(typical) & (typical > 0)
        result["vwap"] = stored.where(~fallback, typical)
        result["vwap"] = result["vwap"].where(np.isfinite(result["vwap"]) & (result["vwap"] > 0))
        estimated = (stored.notna() & quality.eq("estimated")) | fallback
        valid = result["vwap"].notna()
        return result, DailyBarLoader._vwap_report(
            total,
            int((valid & ~estimated).sum()),
            int(estimated.sum()),
            int((~valid).sum()),
        )

    @staticmethod
    def _vwap_report(total: int, provider_rows: int, estimated_rows: int, missing_rows: int) -> dict[str, int | float]:
        def ratio(value: int) -> float:
            return value / total if total else 0.0

        return {
            "valid_rows": provider_rows + estimated_rows,
            "provider_calculated_rows": provider_rows,
            "estimated_rows": estimated_rows,
            "missing_rows": missing_rows,
            "provider_calculated_ratio": ratio(provider_rows),
            "estimated_ratio": ratio(estimated_rows),
            "missing_ratio": ratio(missing_rows),
        }

    @staticmethod
    def _valid_factor(frame: pd.DataFrame) -> pd.Series:
        factors = pd.to_numeric(frame["forward_adjustment_factor"], errors="coerce")
        return factors.notna() & np.isfinite(factors) & (factors > 0)

    @classmethod
    def _adjustment_coverage(cls, frame: pd.DataFrame) -> tuple[dict[str, Any], list[str]]:
        expected = len(frame)
        if frame.empty:
            return {
                "expected_rows": 0,
                "factor_rows": 0,
                "missing_rows": 0,
                "coverage_ratio": 1.0,
                "provider_distribution": {},
            }, []
        valid = cls._valid_factor(frame)
        providers = (
            frame.loc[valid, "adjustment_source"].fillna("unknown").astype(str).value_counts().sort_index().to_dict()
        )
        factor_rows = int(valid.sum())
        sources = sorted(source for source in providers if source != "unknown")
        return {
            "expected_rows": expected,
            "factor_rows": factor_rows,
            "missing_rows": expected - factor_rows,
            "coverage_ratio": factor_rows / expected if expected else 1.0,
            "provider_distribution": {str(key): int(value) for key, value in providers.items()},
        }, sources

    @classmethod
    def _require_complete_adjustments(cls, frame: pd.DataFrame, market: str) -> None:
        if frame.empty:
            return
        missing = frame.loc[~cls._valid_factor(frame), ["instrument", "datetime"]]
        if missing.empty:
            return
        details = []
        for code, group in missing.groupby("instrument", sort=True):
            dates = pd.to_datetime(group["datetime"]).dt.date
            details.append(
                f"market={market} code={code} missing_date_range={dates.min()}..{dates.max()} "
                f"missing_rows={len(group)}"
            )
        raise AdjustmentFactorMissingError("Missing forward adjustment factors: " + "; ".join(details))

    @staticmethod
    def _apply_forward_adjustment(frame: pd.DataFrame) -> pd.DataFrame:
        result = frame.copy()
        factors = pd.to_numeric(result["forward_adjustment_factor"], errors="raise").to_numpy(dtype="float64")
        for column in PRICE_COLUMNS:
            values = pd.to_numeric(result[column], errors="coerce").to_numpy(dtype="float64")
            result[column] = values * factors
        return result

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
            "daily_source_priority",
            "forward_adjustment_factor",
            "adjustment_source",
            "adjustment_source_hash",
        ]
        stable = frame.reindex(columns=columns).copy()
        if not stable.empty:
            stable["datetime"] = pd.to_datetime(stable["datetime"]).dt.strftime("%Y-%m-%d")
        payload = stable.to_csv(index=False, lineterminator="\n", na_rep="<null>", float_format="%.17g")
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


__all__ = ["DailyBarLoadResult", "DailyBarLoader", "PRICE_COLUMNS"]

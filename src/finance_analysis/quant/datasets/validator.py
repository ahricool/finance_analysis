"""Strict validation before a dataset becomes trainable."""

from __future__ import annotations

import pandas as pd

from finance_analysis.quant.price_modes import PriceMode


def validate_daily_bars(
    frame: pd.DataFrame,
    expected_symbols: set[str],
    benchmark_codes: set[str],
    *,
    price_mode: str,
) -> dict:
    errors, warnings = [], []
    required = {"instrument", "datetime", "open", "high", "low", "close", "volume"}
    if missing := required - set(frame.columns): errors.append(f"missing columns: {sorted(missing)}")
    if not errors:
        if frame.duplicated(["instrument", "datetime"]).any(): errors.append("duplicate instrument/datetime rows")
        if frame[list({"open", "high", "low", "close"})].isna().any().any(): errors.append("missing OHLC")
        invalid = (frame[["open", "high", "low", "close"]] <= 0).any(axis=1) | (frame["high"] < frame[["open", "close", "low"]].max(axis=1)) | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
        if invalid.any(): errors.append(f"invalid OHLC rows: {int(invalid.sum())}")
        if (frame["volume"] < 0).any(): errors.append("negative volume")
        if not frame.sort_values(["instrument", "datetime"]).index.equals(frame.index): errors.append("rows are not time sorted")
        actual = set(frame["instrument"].unique())
        if missing_symbols := expected_symbols - actual: errors.append(f"missing instruments: {sorted(missing_symbols)}")
        if missing_benchmarks := benchmark_codes - actual: errors.append(f"missing benchmarks: {sorted(missing_benchmarks)}")
        counts = frame.groupby("instrument")["datetime"].count()
        if len(counts) and counts.min() < counts.max() * 0.6: warnings.append("one or more instruments have large date gaps")
    if price_mode == PriceMode.RAW.value:
        warnings.append("price_mode=raw; raw datasets are diagnostic-only and cannot train production models")
    return {"valid": not errors, "errors": errors, "warnings": warnings, "row_count": len(frame), "symbol_count": int(frame["instrument"].nunique()) if "instrument" in frame else 0}

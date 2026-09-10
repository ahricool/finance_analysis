from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from qlib_worker.datasets.loader import load_features, load_manifest


TRADE_DATE = date(2026, 7, 16)
LOOKBACK_SESSIONS = 80


def _write_dataset(root: Path, dates: pd.DatetimeIndex) -> None:
    for directory in ("calendars", "instruments", "features", "source"):
        (root / directory).mkdir(parents=True, exist_ok=True)
    (root / "calendars" / "day.txt").write_text("\n".join(map(str, dates.date)) + "\n", encoding="utf-8")
    instruments: list[str] = []
    source_rows: list[dict[str, object]] = []
    codes = (("A.US", 0.04), ("B.US", 0.06), ("C.US", 0.08), ("QQQ.US", 0.05))
    origin = pd.Timestamp("2024-01-02")
    for offset, (code, drift) in enumerate(codes):
        instruments.append(f"{code}\t{dates[0].date()}\t{dates[-1].date()}")
        feature_directory = root / "features" / code.lower()
        feature_directory.mkdir()
        global_index = np.array([(day - origin).days for day in dates], dtype=float)
        wave = np.sin(global_index / (11.0 + offset))
        close = 80.0 + offset * 7.0 + global_index * drift + wave
        values = {
            "open": close - 0.15 + wave * 0.02,
            "high": close + 0.6,
            "low": close - 0.6,
            "close": close,
            "vwap": (close + 0.6 + close - 0.6 + close) / 3.0,
            "volume": 100_000.0 + global_index * (10 + offset),
            "factor": np.ones(len(dates)),
        }
        values["amount"] = values["vwap"] * values["volume"]
        for field, data in values.items():
            encoded = np.concatenate((np.array([0], dtype="<f4"), np.asarray(data, dtype="<f4")))
            encoded.tofile(feature_directory / f"{field}.day.bin")
        for index, day in enumerate(dates):
            source_rows.append(
                {
                    "instrument": code,
                    "datetime": day,
                    **{field: float(data[index]) for field, data in values.items()},
                }
            )
    (root / "instruments" / "all.txt").write_text("\n".join(instruments) + "\n", encoding="utf-8")
    pd.DataFrame(source_rows).to_csv(root / "source" / "daily.csv", index=False)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "date_from": str(dates[0].date()),
                "date_to": str(dates[-1].date()),
                "symbols": ["A.US", "B.US", "C.US"],
                "benchmark_codes": ["QQQ.US"],
                "market_benchmark": "QQQ.US",
            }
        ),
        encoding="utf-8",
    )


def _trade_date_features(root: Path) -> pd.DataFrame:
    features = load_features(root, load_manifest(root), {"base": "Alpha158"})
    rows = features[features.index.get_level_values("datetime") == pd.Timestamp(TRADE_DATE)]
    if rows.empty:
        raise AssertionError(f"No Alpha158 rows for {TRADE_DATE} in {root}")
    return rows.sort_index()


def _assert_same_trade_date_features(left: pd.DataFrame, right: pd.DataFrame, label: str) -> None:
    assert list(left.columns) == list(right.columns), label
    assert list(left.index.get_level_values("instrument")) == list(right.index.get_level_values("instrument")), label
    left_nan = left.isna()
    right_nan = right.isna()
    assert left_nan.equals(right_nan), f"{label} NaN state differs"
    comparable = left.where(~left_nan)
    other = right.where(~right_nan)
    pd.testing.assert_frame_equal(
        comparable,
        other,
        check_exact=False,
        rtol=1e-5,
        atol=1e-5,
        obj=label,
    )


def test_alpha158_trade_date_features_match_across_lookback_windows(tmp_path: Path) -> None:
    full_dates = pd.bdate_range(TRADE_DATE - timedelta(days=520), TRADE_DATE)
    assert full_dates[-1].date() == TRADE_DATE
    baseline_root = tmp_path / "calendar-500"
    _write_dataset(baseline_root, full_dates[full_dates.date >= TRADE_DATE - timedelta(days=500)])
    baseline = _trade_date_features(baseline_root)

    for calendar_days in (500, 300, 250, 200):
        dates = full_dates[full_dates.date >= TRADE_DATE - timedelta(days=calendar_days)]
        root = tmp_path / f"calendar-{calendar_days}"
        if calendar_days == 500:
            current = baseline
        else:
            _write_dataset(root, dates)
            current = _trade_date_features(root)
        _assert_same_trade_date_features(baseline, current, f"{calendar_days} calendar days")
        assert len(dates) >= LOOKBACK_SESSIONS

    session_dates = full_dates[-LOOKBACK_SESSIONS:]
    session_root = tmp_path / "sessions-80"
    _write_dataset(session_root, session_dates)
    session_features = _trade_date_features(session_root)
    _assert_same_trade_date_features(baseline, session_features, "80 trading sessions")
    assert len(session_dates) == LOOKBACK_SESSIONS

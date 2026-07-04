from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from qlib_worker.datasets.loader import load_features, load_manifest


def _write_minimal_dataset(root: Path) -> None:
    dates = pd.bdate_range("2024-01-02", periods=260)
    (root / "calendars").mkdir(parents=True)
    (root / "instruments").mkdir()
    (root / "features").mkdir()
    (root / "source").mkdir()
    (root / "calendars" / "day.txt").write_text("\n".join(map(str, dates.date)) + "\n")
    instruments = []
    source_rows = []
    for offset, code in enumerate(("A.US", "QQQ.US")):
        instruments.append(f"{code}\t{dates[0].date()}\t{dates[-1].date()}")
        directory = root / "features" / code.lower()
        directory.mkdir()
        close = 100.0 + offset + np.arange(len(dates)) * (0.05 + offset * 0.01)
        values = {
            "open": close - 0.2,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "vwap": close + 0.05,
            "volume": np.full(len(dates), 100_000.0),
            "amount": (close + 0.05) * 100_000.0,
            "factor": np.ones(len(dates)),
        }
        for field, data in values.items():
            np.concatenate((np.array([0], dtype="<f4"), np.asarray(data, dtype="<f4"))).tofile(
                directory / f"{field}.day.bin"
            )
        for index, day in enumerate(dates):
            source_rows.append(
                {
                    "instrument": code,
                    "datetime": day,
                    **{field: float(data[index]) for field, data in values.items()},
                }
            )
    (root / "instruments" / "all.txt").write_text("\n".join(instruments) + "\n")
    pd.DataFrame(source_rows).to_csv(root / "source" / "daily.csv", index=False)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "date_from": str(dates[0].date()),
                "date_to": str(dates[-1].date()),
                "symbols": ["A.US"],
                "benchmark_codes": ["QQQ.US"],
                "market_benchmark": "QQQ.US",
                "sector_benchmark_mapping": {},
            }
        )
    )


def test_alpha158_reads_exported_vwap(tmp_path: Path) -> None:
    _write_minimal_dataset(tmp_path)
    features = load_features(tmp_path, load_manifest(tmp_path), {"ablation": "base_only"})
    assert features.shape[1] >= 150
    assert features.notna().any(axis=1).sum() > 0

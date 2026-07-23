"""Dataset-level checks that can run inside the Qlib environment."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from qlib_worker.datasets.loader import load_features, load_manifest


def validate_dataset(dataset: Path) -> dict[str, Any]:
    manifest = load_manifest(dataset)
    vwap_files = list((dataset / "features").glob("*/vwap.day.bin"))
    if not vwap_files:
        raise ValueError("Dataset has no vwap feature binaries")
    features = load_features(dataset, manifest, {"base": "Alpha158"})
    if features.empty:
        raise ValueError("Alpha158 produced no features")
    return {
        "valid": True,
        "alpha158_rows": int(len(features)),
        "alpha158_columns": int(len(features.columns)),
        "vwap_instruments": len(vwap_files),
    }

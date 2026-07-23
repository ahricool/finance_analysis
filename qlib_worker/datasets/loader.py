"""Load immutable Qlib dataset snapshots and initialize Qlib per task."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import qlib
from qlib.constant import REG_US
from qlib.contrib.data.handler import Alpha158


def load_manifest(dataset: Path) -> dict[str, Any]:
    manifest_path = dataset / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError("Dataset manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = {"date_from", "date_to", "symbols", "benchmark_codes"}
    missing = sorted(required - manifest.keys())
    if missing:
        raise ValueError(f"Dataset manifest missing fields: {missing}")
    return manifest


def load_features(
    dataset: Path,
    manifest: dict[str, Any],
    feature_config: dict[str, Any] | None = None,
) -> pd.DataFrame:
    # The worker process is replaced after every task. Initializing here avoids
    # retaining a provider/cache configured for a previous dataset.
    qlib.init(provider_uri=str(dataset), region=REG_US, kernels=1)
    handler = Alpha158(
        instruments="all",
        start_time=manifest["date_from"],
        end_time=manifest["date_to"],
        fit_start_time=manifest["date_from"],
        fit_end_time=manifest["date_to"],
    )
    features = handler.fetch(col_set="feature")
    if list(features.index.names) == ["instrument", "datetime"]:
        features = features.swaplevel()
    features.index = features.index.set_names(["datetime", "instrument"])
    features.columns = [
        "_".join(map(str, column)) if isinstance(column, tuple) else str(column) for column in features.columns
    ]
    config = feature_config or {}
    if set(config) - {"base"} or config.get("base", "Alpha158") != "Alpha158":
        raise ValueError(
            "Only Alpha158 features are supported; legacy custom-feature models must be retrained"
        )
    return features.replace([np.inf, -np.inf], np.nan).sort_index()

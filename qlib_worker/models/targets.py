"""Forward-return labels with model-type production semantics."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

CROSS_SECTION_MODEL_KEY = "cross_section_lgbm"
TIME_SERIES_MODEL_KEY = "time_series_lgbm"
DEFAULT_PREDICTION_HORIZON = 5
SHARED_ENTRY_PRICE = "open"
SHARED_EXIT_PRICE = "close"


def production_target_config(model_key: str) -> dict[str, Any]:
    if model_key not in {CROSS_SECTION_MODEL_KEY, TIME_SERIES_MODEL_KEY}:
        raise ValueError(f"Unknown model_key: {model_key}")
    if model_key == CROSS_SECTION_MODEL_KEY:
        semantics = {"benchmark": "market", "excess_return": True}
    else:
        semantics = {"benchmark": "none", "excess_return": False}
    return {
        "prediction_horizon": DEFAULT_PREDICTION_HORIZON,
        "entry_price": SHARED_ENTRY_PRICE,
        "exit_price": SHARED_EXIT_PRICE,
        **semantics,
    }


def resolve_target_config(model_key: str, raw: Mapping[str, Any] | None) -> dict[str, Any]:
    del raw
    return production_target_config(model_key)


@dataclass(frozen=True)
class TargetConfig:
    prediction_horizon: int = DEFAULT_PREDICTION_HORIZON
    benchmark: str = "market"
    entry_price: str = SHARED_ENTRY_PRICE
    exit_price: str = SHARED_EXIT_PRICE
    excess_return: bool = True

    @classmethod
    def parse(cls, raw: dict[str, Any], default_horizon: int) -> "TargetConfig":
        normalized = dict(raw)
        if "entry" in normalized and "entry_price" not in normalized:
            normalized["entry_price"] = str(normalized.pop("entry")).split()[-1]
        if "exit" in normalized and "exit_price" not in normalized:
            exit_value = str(normalized.pop("exit"))
            normalized["exit_price"] = exit_value.split()[-1]
        normalized.setdefault("prediction_horizon", default_horizon)
        allowed = set(cls.__dataclass_fields__)
        unknown = sorted(set(normalized) - allowed)
        if unknown:
            raise ValueError(f"Unknown target_config parameters: {unknown}")
        config = cls(**normalized)
        if int(config.prediction_horizon) < 1:
            raise ValueError("prediction_horizon must be positive")
        if config.entry_price not in {"open", "close"} or config.exit_price not in {"open", "close"}:
            raise ValueError("entry_price and exit_price must be open or close")
        if config.benchmark not in {"market", "none"}:
            raise ValueError("benchmark must be market or none")
        return cls(**{**asdict(config), "prediction_horizon": int(config.prediction_horizon)})

    @classmethod
    def for_model(cls, model_key: str, raw: Mapping[str, Any] | None) -> "TargetConfig":
        payload = dict(raw or {})
        if "prediction_horizon" in payload and int(payload["prediction_horizon"]) != DEFAULT_PREDICTION_HORIZON:
            raise ValueError("production prediction_horizon must be 5")
        return cls.parse(resolve_target_config(model_key, payload), DEFAULT_PREDICTION_HORIZON)


def build_target(dataset: Path, manifest: dict[str, Any], config: TargetConfig) -> pd.Series:
    bars = pd.read_csv(dataset / "source" / "daily.csv", parse_dates=["datetime"]).sort_values(
        ["instrument", "datetime"]
    )
    grouped = {code: frame.set_index("datetime") for code, frame in bars.groupby("instrument")}
    benchmark_codes = set(manifest["benchmark_codes"])
    market_benchmark = manifest.get("market_benchmark") or next(iter(benchmark_codes), None)
    rows: list[tuple[pd.Timestamp, str, float]] = []
    for code, frame in grouped.items():
        if code in benchmark_codes:
            continue
        stock_return = _forward_return(frame, config)
        values = stock_return
        if config.excess_return and config.benchmark == "market":
            if not market_benchmark:
                raise ValueError(f"No market benchmark configured for {code}")
            benchmark = grouped.get(market_benchmark)
            if benchmark is None:
                raise ValueError(f"Market benchmark data missing for {code}: {market_benchmark}")
            values = stock_return - _forward_return(benchmark, config).reindex(stock_return.index)
        rows.extend((day, code, float(value * 100.0)) for day, value in values.items() if np.isfinite(value))
    if not rows:
        raise ValueError("Target configuration produced no labels")
    return (
        pd.DataFrame(rows, columns=["datetime", "instrument", "label"])
        .set_index(["datetime", "instrument"])["label"]
        .sort_index()
    )


def _forward_return(frame: pd.DataFrame, config: TargetConfig) -> pd.Series:
    entry = frame[config.entry_price].shift(-1)
    exit_value = frame[config.exit_price].shift(-config.prediction_horizon)
    return exit_value / entry - 1.0

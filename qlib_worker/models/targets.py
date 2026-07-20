"""Forward-return labels driven entirely by target_config."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class TargetConfig:
    prediction_horizon: int = 5
    benchmark: str = "sector_or_market"
    entry_price: str = "open"
    exit_price: str = "close"
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
        if config.benchmark not in {"sector_or_market", "sector_or_qqq", "market", "sector", "none"}:
            raise ValueError(
                "benchmark must be sector_or_market, sector_or_qqq, market, sector, or none"
            )
        return cls(**{**asdict(config), "prediction_horizon": int(config.prediction_horizon)})


def build_target(dataset: Path, manifest: dict[str, Any], config: TargetConfig) -> pd.Series:
    bars = pd.read_csv(dataset / "source" / "daily.csv", parse_dates=["datetime"]).sort_values(
        ["instrument", "datetime"]
    )
    grouped = {code: frame.set_index("datetime") for code, frame in bars.groupby("instrument")}
    benchmark_codes = set(manifest["benchmark_codes"])
    market_benchmark = manifest.get("market_benchmark") or next(iter(benchmark_codes), None)
    sector_mapping = manifest.get("sector_benchmark_mapping", {})
    rows: list[tuple[pd.Timestamp, str, float]] = []
    for code, frame in grouped.items():
        if code in benchmark_codes:
            continue
        stock_return = _forward_return(frame, config)
        values = stock_return
        if config.excess_return and config.benchmark != "none":
            benchmark_code = _benchmark_code(code, config.benchmark, sector_mapping, market_benchmark)
            benchmark = grouped.get(benchmark_code)
            if benchmark is None:
                raise ValueError(f"Benchmark data missing for {code}: {benchmark_code}")
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


def _benchmark_code(
    code: str,
    benchmark: str,
    sector_mapping: dict[str, str | None],
    market_benchmark: str | None,
) -> str:
    if benchmark == "market":
        candidate = market_benchmark
    elif benchmark == "sector":
        candidate = sector_mapping.get(code)
    else:
        candidate = sector_mapping.get(code) or market_benchmark
    if not candidate:
        raise ValueError(f"No benchmark configured for {code}")
    return candidate

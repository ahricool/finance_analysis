"""Environment-backed, versionable defaults for quant experiments."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from finance_analysis.core.paths import get_data_dir


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def _ratio(name: str, default: float) -> float:
    value = _float(name, default)
    if not 0 < value <= 1:
        raise ValueError(f"{name} must be greater than 0 and at most 1, got {value}")
    return value


@dataclass(frozen=True)
class RegimeConfig:
    risk_on_threshold: float = 0.65
    risk_off_threshold: float = 0.35
    component_weights: dict[str, float] = field(
        default_factory=lambda: {
            "trend_ma20": 0.15,
            "trend_ma60": 0.15,
            "momentum_20d": 0.10,
            "breadth_up": 0.10,
            "breadth_ma20": 0.10,
            "breadth_ma60": 0.10,
            "realized_volatility_20d": 0.12,
            "max_drawdown_60d": 0.08,
            "style_relative_20d": 0.10,
        }
    )
    normalization_ranges: dict[str, tuple[float, float]] = field(
        default_factory=lambda: {
            "trend_ma20": (-0.05, 0.05),
            "trend_ma60": (-0.10, 0.10),
            "momentum_20d": (-0.10, 0.10),
            "realized_volatility_20d": (0.10, 0.45),
            "max_drawdown_60d": (-0.25, 0.0),
            "style_relative_20d": (-0.08, 0.08),
        }
    )
    exposure_curve: tuple[tuple[float, float], ...] = (
        (0.00, 0.10),
        (0.20, 0.10),
        (0.35, 0.20),
        (0.50, 0.40),
        (0.65, 0.60),
        (0.80, 0.75),
        (1.00, 0.80),
    )

    def validate(self) -> None:
        if not 0 <= self.risk_off_threshold < self.risk_on_threshold <= 1:
            raise ValueError("Regime thresholds must be ordered within [0, 1]")
        if not self.component_weights or any(weight < 0 for weight in self.component_weights.values()):
            raise ValueError("Regime component weights must be non-negative")
        if abs(sum(self.component_weights.values()) - 1.0) > 1e-9:
            raise ValueError("Regime component weights must sum to 1")
        if set(self.normalization_ranges) != {
            "trend_ma20",
            "trend_ma60",
            "momentum_20d",
            "realized_volatility_20d",
            "max_drawdown_60d",
            "style_relative_20d",
        }:
            raise ValueError("Regime normalization ranges are incomplete")
        if any(lower >= upper for lower, upper in self.normalization_ranges.values()):
            raise ValueError("Regime normalization ranges must be increasing")
        if len(self.exposure_curve) < 2:
            raise ValueError("Regime exposure curve requires at least two points")
        scores = [score for score, _ in self.exposure_curve]
        exposures = [exposure for _, exposure in self.exposure_curve]
        if scores[0] != 0 or scores[-1] != 1 or any(
            left >= right for left, right in zip(scores, scores[1:])
        ):
            raise ValueError("Regime exposure score points must increase from 0 to 1")
        if any(not 0 <= exposure <= 1 for exposure in exposures) or any(
            left > right for left, right in zip(exposures, exposures[1:])
        ):
            raise ValueError("Regime exposure values must be non-decreasing within [0, 1]")


@dataclass(frozen=True)
class FusionConfig:
    cross_section_weight: float = 0.60
    time_series_weight: float = 0.40
    sector_weight: float = 0.10
    regime_multipliers: dict[str, float] = field(
        default_factory=lambda: {"risk_on": 1.0, "neutral": 0.7, "risk_off": 0.3}
    )
    regime_position_limits: dict[str, float] = field(
        default_factory=lambda: {"risk_on": 0.08, "neutral": 0.05, "risk_off": 0.02}
    )

    def validate(self) -> None:
        total = self.cross_section_weight + self.time_series_weight
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"Fusion weights must sum to 1, got {total}")
        if not 0 <= self.sector_weight <= 1:
            raise ValueError("sector_weight must be between 0 and 1")


@dataclass(frozen=True)
class PortfolioConfig:
    buy_top_k: int = 5
    watch_top_k: int = 10
    hold_rank_threshold: int = 15
    sell_rank_threshold: int = 20
    single_stock_max_weight: float = 0.08
    sector_max_weight: float = 0.30
    minimum_liquidity: float = 1_000_000
    maximum_daily_new_exposure: float = 0.20
    maximum_daily_turnover: float = 0.30
    weighting: str = "equal_weight"


@dataclass(frozen=True)
class IntradayConfig:
    minimum_bars: int = 30
    minimum_volume_ratio: float = 0.8
    maximum_opening_gap: float = 0.05
    maximum_drawdown: float = 0.03


@dataclass(frozen=True)
class QuantConfig:
    feature_version: str = "daily-v1"
    regime_model_version: str = "regime-rules-v2"
    sector_model_version: str = "sector-rules-v1"
    artifact_root: Path = field(
        default_factory=lambda: Path(os.getenv("QUANT_ARTIFACT_ROOT", get_data_dir() / "quant"))
    )
    cache_ttl_seconds: int = field(default_factory=lambda: int(os.getenv("QUANT_CACHE_TTL_SECONDS", "86400")))
    minimum_universe_coverage: float = field(
        default_factory=lambda: _ratio("QUANT_MIN_UNIVERSE_COVERAGE", 0.90)
    )
    regime: RegimeConfig = field(default_factory=RegimeConfig)
    fusion: FusionConfig = field(default_factory=FusionConfig)
    portfolio: PortfolioConfig = field(default_factory=PortfolioConfig)
    intraday: IntradayConfig = field(default_factory=IntradayConfig)

    def version_payload(self) -> dict:
        value = asdict(self)
        value["artifact_root"] = str(self.artifact_root)
        return value


def get_quant_config() -> QuantConfig:
    return QuantConfig()

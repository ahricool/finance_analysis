"""Environment-backed, versionable defaults for quant experiments."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from finance_analysis.core.paths import get_data_dir


def _float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


@dataclass(frozen=True)
class RegimeConfig:
    risk_on_exposure: float = 0.80
    neutral_exposure: float = 0.40
    risk_off_exposure: float = 0.10
    risk_on_threshold: float = 0.65
    risk_off_threshold: float = 0.35


@dataclass(frozen=True)
class FusionConfig:
    cross_section_weight: float = 0.45
    time_series_weight: float = 0.30
    event_weight: float = 0.25
    regime_multipliers: dict[str, float] = field(
        default_factory=lambda: {"risk_on": 1.0, "neutral": 0.7, "risk_off": 0.3}
    )
    regime_position_limits: dict[str, float] = field(
        default_factory=lambda: {"risk_on": 0.08, "neutral": 0.05, "risk_off": 0.02}
    )

    def validate(self) -> None:
        total = self.cross_section_weight + self.time_series_weight + self.event_weight
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"Fusion weights must sum to 1, got {total}")


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
    event_feature_version: str = "event-v1"
    regime_model_version: str = "regime-rules-v1"
    sector_model_version: str = "sector-rules-v1"
    artifact_root: Path = field(
        default_factory=lambda: Path(os.getenv("QUANT_ARTIFACT_ROOT", get_data_dir() / "quant"))
    )
    cache_ttl_seconds: int = field(default_factory=lambda: int(os.getenv("QUANT_CACHE_TTL_SECONDS", "86400")))
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

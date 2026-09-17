"""FA v1 observation thresholds, not upstream signals or return-validated rules."""

from dataclasses import dataclass
from datetime import time


@dataclass(frozen=True)
class SentimentConfig:
    version: str = "fa-market-sentiment-v1"
    scope: str = "is_st=false AND is_new=false"
    early_time: time = time(10, 0)
    history_days: int = 20
    limit_weight: float = 0.60
    multi_weight: float = 0.40
    ice: float = 20
    repair_base: float = 35
    active: float = 60
    climax: float = 85
    heat_change: float = 15
    quality_drop: float = 0.10
    quality_confirmation: float = 0.60
    minimum_coverage: float = 0.80
    minimum_promotion_cohort: int = 5
    max_backfill_days: int = 31

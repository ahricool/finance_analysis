"""BTC strategy configuration."""

from dataclasses import dataclass
from functools import lru_cache

from finance_analysis.config.env_parsing import env_bool, env_str


@dataclass(frozen=True)
class CryptoConfig:
    enabled: bool = True
    rest_base_url: str = "https://data-api.binance.vision"

    def __post_init__(self):
        if not self.rest_base_url.startswith("https://"):
            raise ValueError("Binance endpoint requires HTTPS")


@lru_cache(maxsize=1)
def get_crypto_config() -> CryptoConfig:
    return CryptoConfig(
        enabled=env_bool("CRYPTO_ENABLED", True),
        rest_base_url=env_str("BINANCE_REST_BASE_URL", "https://data-api.binance.vision"),
    )

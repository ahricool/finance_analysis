"""Configuration for the single-symbol BTC V0.1 module."""

from dataclasses import dataclass
from functools import lru_cache

from finance_analysis.config.env_parsing import env_bool, env_int, env_str


@dataclass(frozen=True)
class CryptoConfig:
    enabled: bool = True
    symbol: str = "BTCUSDT"
    rest_base_url: str = "https://api.binance.com"
    ws_base_url: str = "wss://stream.binance.com:9443"
    http_fallback_interval_seconds: int = 60
    ws_reconnect_interval_seconds: int = 60
    ws_timeout_seconds: int = 20
    initial_history_days: int = 30

    def __post_init__(self):
        if self.symbol != "BTCUSDT":
            raise ValueError("Crypto V0.1 only supports BTCUSDT")
        if not self.rest_base_url.startswith("https://") or not self.ws_base_url.startswith("wss://"):
            raise ValueError("Binance endpoints require HTTPS/WSS")


@lru_cache(maxsize=1)
def get_crypto_config() -> CryptoConfig:
    return CryptoConfig(
        enabled=env_bool("CRYPTO_ENABLED", True),
        symbol=env_str("CRYPTO_SYMBOL", "BTCUSDT"),
        rest_base_url=env_str("BINANCE_REST_BASE_URL", "https://api.binance.com"),
        ws_base_url=env_str("BINANCE_WS_BASE_URL", "wss://stream.binance.com:9443"),
        http_fallback_interval_seconds=env_int("CRYPTO_HTTP_FALLBACK_INTERVAL_SECONDS", 60, minimum=10),
        ws_reconnect_interval_seconds=env_int("CRYPTO_WS_RECONNECT_INTERVAL_SECONDS", 60, minimum=10),
        ws_timeout_seconds=env_int("CRYPTO_WS_TIMEOUT_SECONDS", 20, minimum=5),
        initial_history_days=env_int("CRYPTO_INITIAL_HISTORY_DAYS", 30, minimum=4, maximum=90),
    )

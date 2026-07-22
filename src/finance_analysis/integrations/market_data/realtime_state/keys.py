"""Central Redis key definitions for realtime market state."""

LEADER_LOCK_KEY = "lock:market_stream:leader"
STREAMER_HEARTBEAT_KEY = "rt:streamer:heartbeat"


def quote_key(symbol: str) -> str:
    return f"rt:quote:{symbol}"


def current_candle_key(symbol: str) -> str:
    return f"rt:candle:1m:{symbol}:current"


def bars_index_key(symbol: str) -> str:
    return f"rt:bars:1m:{symbol}:index"


def bars_data_key(symbol: str) -> str:
    return f"rt:bars:1m:{symbol}:data"


def trend_key(symbol: str) -> str:
    return f"rt:trend:1m:{symbol}"


def pattern_key(symbol: str) -> str:
    return f"rt:pattern:1m:{symbol}"


def subscription_key(symbol: str) -> str:
    return f"rt:subscription:{symbol}"

"""Code-defined BTC research strategies. Keys are durable versioned identities."""

from dataclasses import dataclass
from typing import Callable

from finance_analysis.crypto.strategy import evaluate

BREAKOUT_KEY = "btc_breakout_v1"
SYMBOL = "BTCUSDT"


@dataclass(frozen=True)
class StrategyDefinition:
    key: str
    display_name: str
    evaluate: Callable
    enabled: bool = True


STRATEGIES = (StrategyDefinition(BREAKOUT_KEY, "Breakout V1", evaluate),)

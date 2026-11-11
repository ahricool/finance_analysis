"""Versioned, provisional scoring parameters and the user-selected fixed universe."""

from dataclasses import dataclass

SYMBOLS = tuple(
    f"{code}.US"
    for code in (
        "SPY",
        "QQQ",
        "NVDA",
        "IWM",
        "TSLA",
        "AMD",
        "TLT",
        "SPCX",
        "AAPL",
        "MU",
        "AMZN",
        "CRWV",
        "HYG",
        "MSFT",
        "IBIT",
        "GLD",
        "INTC",
        "IREN",
        "SOXL",
        "AVGO",
        "GFL",
        "TQQQ",
        "SOFI",
        "GOOGL",
        "SLV",
        "MARA",
        "MSTR",
        "RIOT",
        "HIMS",
        "META",
    )
)
VERSION = "intraday_options_v2"
WINDOWS = (15, 30, 60)
WINDOW_WEIGHTS = (0.30, 0.45, 0.25)


@dataclass(frozen=True)
class ScoringConfig:
    stability_weight: float = 0.30
    efficiency_weight: float = 0.30
    strength_weight: float = 0.25
    disturbance_weight: float = 0.15
    # Log-return floors: 2bp neutral band, 5bp full movement gate.
    neutral_move: float = 0.0002
    full_move: float = 0.0005
    neutral_strength: float = 0.35
    full_gate_strength: float = 0.60
    full_strength: float = 2.0
    neutral_efficiency: float = 0.15
    impulse_concentration: float = 0.60
    recent_extension_fraction: float = 0.15
    impulse_cap: float = 35.0
    extension_atr: float = 2.5
    stale_seconds: int = 90
    close_grace_seconds: int = 15


CONFIG = ScoringConfig()

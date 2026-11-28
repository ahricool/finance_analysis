"""Versioned, provisional scoring parameters and QQQ (Nasdaq-100) intraday universe."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

UNIVERSE_KEY = "us_nasdaq100"
BENCHMARK_SYMBOLS = ("SPY.US", "QQQ.US")
BENCHMARK_SYMBOL_SET = frozenset(BENCHMARK_SYMBOLS)
# Deduplicate dual-class Alphabet share (keep GOOGL.US alongside QQQ constituents).
EXCLUDED_DUAL_CLASS_SYMBOLS = frozenset({"GOOG.US"})

# Code fallback snapshot of SPY/QQQ + active us_nasdaq100 constituents (excluding GOOG.US);
# live runtime dynamically reads PostgreSQL universe `us_nasdaq100` via intraday_simulation.load_universe_symbols().
_FALLBACK_CONSTITUENT_CODES = (
    "AAPL",
    "ABNB",
    "ADBE",
    "ADI",
    "ADP",
    "ADSK",
    "AEP",
    "ALAB",
    "ALNY",
    "AMAT",
    "AMD",
    "AMGN",
    "AMZN",
    "APP",
    "ARM",
    "ASML",
    "AVGO",
    "AXON",
    "BKNG",
    "BKR",
    "CCEP",
    "CDNS",
    "CEG",
    "CMCSA",
    "COST",
    "CPRT",
    "CRWD",
    "CRWV",
    "CSCO",
    "CSX",
    "CTAS",
    "DASH",
    "DDOG",
    "DXCM",
    "EXC",
    "FANG",
    "FAST",
    "FER",
    "FTNT",
    "GEHC",
    "GILD",
    "GOOGL",
    "HON",
    "HONA",
    "IDXX",
    "INTC",
    "INTU",
    "ISRG",
    "KDP",
    "KLAC",
    "LIN",
    "LITE",
    "LRCX",
    "MAR",
    "MCHP",
    "MDLZ",
    "MELI",
    "META",
    "MNST",
    "MPWR",
    "MRNA",
    "MRVL",
    "MSFT",
    "MSTR",
    "MU",
    "NBIS",
    "NFLX",
    "NVDA",
    "NXPI",
    "ODFL",
    "ORLY",
    "PANW",
    "PAYX",
    "PCAR",
    "PDD",
    "PEP",
    "PLTR",
    "PYPL",
    "QCOM",
    "REGN",
    "RKLB",
    "ROP",
    "ROST",
    "SBUX",
    "SHOP",
    "SNDK",
    "SNPS",
    "SPCX",
    "STX",
    "TER",
    "TMUS",
    "TRI",
    "TSLA",
    "TTWO",
    "TXN",
    "VRTX",
    "WDAY",
    "WDC",
    "WMT",
    "XEL",
)

SYMBOLS = (
    *BENCHMARK_SYMBOLS,
    *tuple(f"{code}.US" for code in _FALLBACK_CONSTITUENT_CODES),
)
VERSION = "intraday_options_v19"
WINDOWS = (5, 15, 30, 60)
COMPOSITE_WINDOWS = (15, 30, 60)
WINDOW_WEIGHTS = (0.30, 0.45, 0.25)


def normalize_universe_symbols(raw_codes: Iterable[str]) -> tuple[str, ...]:
    """Normalize DB universe codes: canonical `.US`, drop dual-class duplicates, prepend SPY/QQQ."""
    members: set[str] = set()
    for raw in raw_codes:
        code = str(raw or "").strip().upper()
        if not code or not code.endswith(".US") or code.startswith("."):
            continue
        if code in EXCLUDED_DUAL_CLASS_SYMBOLS or code in BENCHMARK_SYMBOL_SET:
            continue
        members.add(code)
    if not members:
        return ()
    return (*BENCHMARK_SYMBOLS, *sorted(members))


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

"""Fixed display semantics and transparent V1 risk contributions."""

from dataclasses import dataclass

UNIVERSE_KEY = "us_macro"


@dataclass(frozen=True)
class MacroInstrument:
    name: str
    category: str
    instrument_type: str = "ETF"


MACRO_INSTRUMENTS = {
    "SPY.US": MacroInstrument("S&P 500", "EQUITY"),
    "QQQ.US": MacroInstrument("Nasdaq 100", "EQUITY"),
    "TLT.US": MacroInstrument("Long Treasury", "RATES"),
    "UUP.US": MacroInstrument("US Dollar", "DOLLAR"),
    "USO.US": MacroInstrument("Crude Oil", "COMMODITY"),
    "GLD.US": MacroInstrument("Gold", "COMMODITY"),
    "HYG.US": MacroInstrument("High Yield Credit", "CREDIT"),
    "LQD.US": MacroInstrument("Investment Grade Credit", "CREDIT"),
    "IWM.US": MacroInstrument("Russell 2000", "RISK"),
    "SMH.US": MacroInstrument("Semiconductor", "RISK"),
    "XLY.US": MacroInstrument("Consumer Discretionary", "RISK"),
    "XLP.US": MacroInstrument("Consumer Staples", "DEFENSIVE"),
    "VIX.US": MacroInstrument("VIX", "VOLATILITY", "INDEX"),
}


@dataclass(frozen=True)
class MacroRatio:
    numerator: str
    denominator: str
    name: str


MACRO_RATIOS = {
    "HYG_LQD": MacroRatio("HYG.US", "LQD.US", "High Yield / Investment Grade"),
    "IWM_SPY": MacroRatio("IWM.US", "SPY.US", "Small Cap / S&P 500"),
    "SMH_SPY": MacroRatio("SMH.US", "SPY.US", "Semiconductor / S&P 500"),
    "XLY_XLP": MacroRatio("XLY.US", "XLP.US", "Discretionary / Staples"),
}

# key, risk-on trend, maximum points; sum = 100. NEUTRAL earns half.
# TLT is a small defensive-demand proxy, not a causal interest-rate model.
RISK_SIGNALS = (
    ("SPY.US", "UP", 15),
    ("QQQ.US", "UP", 10),
    ("HYG_LQD", "UP", 15),
    ("IWM_SPY", "UP", 10),
    ("SMH_SPY", "UP", 10),
    ("XLY_XLP", "UP", 10),
    ("VIX.US", "DOWN", 20),
    ("TLT.US", "DOWN", 5),
    ("UUP.US", "DOWN", 5),
)
MIN_SIGNAL_COVERAGE = 0.65

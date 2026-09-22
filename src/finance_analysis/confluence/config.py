"""V1 heuristics, not backtested probabilities or trading recommendations."""

ALGORITHM_VERSION = "confluence_v1"
WEIGHTS = {"industry": 25, "trend": 30, "quant": 20, "etf": 15, "dragon_tiger": 10}
MIN_SIGNALS = 3
STRONG_MIN_SIGNALS = 4
STRONG_MIN_POSITIVE = 3
STRONG_MIN_SCORE = 75
TOP_INDUSTRY = 10
TOP_QUANT = 20
TOP_ETF = 10
LOW_FRAGILITY = 30
HIGH_FRAGILITY = 70
EARLY_LIFECYCLES = {"IGNITION", "EMERGING"}
POSITIVE_LIFECYCLES = EARLY_LIFECYCLES | {"EXPANSION"}
# A dimension contributes its full weight, half weight, or zero weight.
FACTORS = {"positive": 1.0, "neutral": 0.5, "negative": 0.0}
SOURCE_MODULES = {
    "industry": "industry_strength",
    "trend": "trend_following",
    "quant": "quant",
    "etf": "etf_rotation",
    "dragon_tiger": "dragon_tiger_flow",
}

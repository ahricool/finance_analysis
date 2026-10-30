"""V2 heuristic rules, not backtest-validated. Returns use decimal units."""

from finance_analysis.trend_following.config import DEFAULT_CONFIG as TREND_CONFIG

RULE_VERSION = "intraday_v2"
TREND_TOP = 30
ETF_TOP = 5
BENCHMARKS = TREND_CONFIG.benchmark_codes
PROVIDERS = {"CN": ("easyquotation", ("sina_intraday", "tencent_intraday")), "US": ("yfinance", ("yfinance",))}
BAR_MINUTES = 1
WINDOWS = (5, 15, 30)
OPENING_MINUTES = 5
BREAK_BUFFER = 0.001
BREAK_BARS = 2
STABLE_EVALUATIONS = 2
STABLE_SECONDS = 240
MAX_OBSERVATION_GAP_SECONDS = 600
MAX_DATA_AGE_SECONDS = 300  # Delayed Yahoo data is exposed; older evidence cannot change state.
MAX_COMPARISON_SKEW_SECONDS = 120
VOLUME_DAYS = 20
VOLUME_LOW = 0.8
VOLUME_EXPANDING = 1.2
RS_CONFIRM = 0.003
RS_WEAK = -0.008
SESSION_MEAN_WEAK = -0.005
GAP_FLAT = 0.003
GAP_OBVIOUS = 0.02
GAP_EXCESSIVE = 0.05
GAP_FADE = -0.015
CHASE_RETURN = 0.08
CHASE_SESSION_MEAN = 0.035
CHASE_INTRADAY = 0.05
TREND_SCORE_DECAY = 5
SCORE_WEIGHTS = {"price": 60, "relative_strength": 25, "volume": 5, "trend": 10}
RISK_PENALTY = {"LOW": 0, "MEDIUM": 5, "HIGH": 10}
HISTORY_CALENDAR_DAYS = 120
FREEZE_LEAD_MINUTES = 10

# Entire quote/minute/history phase, leaving time for calculation and PostgreSQL publication.
MARKET_DATA_BUDGET_SECONDS = 210
MARKET_DATA_RETURN_RESERVE_SECONDS = 2

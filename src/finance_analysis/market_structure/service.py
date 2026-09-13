"""Background closing calculation; the read facade never invokes this engine."""

import math
from collections import defaultdict
from datetime import date, timedelta
from statistics import fmean

from finance_analysis.database.repositories.market_structure import MarketStructureRepository
from finance_analysis.integrations.market_data.service import MarketDataService
from finance_analysis.market_review.trading_calendar import (
    get_effective_trading_date,
    get_trading_days_between,
    is_market_open,
    is_market_session_closed,
)
from finance_analysis.trend_following.config import DEFAULT_CONFIG as TREND_CONFIG
from .config import DEFAULT_CONFIG
from .metrics import breadth, leadership, rotation_metrics, states
from .universe import get_universe_codes, universe_key


class MarketStructureService:
    def __init__(self, market, repository=None, config=DEFAULT_CONFIG, *, market_data=None):
        self.market = market.upper()
        if self.market not in {"CN", "US"}:
            raise ValueError("market must be CN or US")
        self.repository = repository or MarketStructureRepository(self.market)
        self.config = config
        self.market_data = market_data or MarketDataService()

    def run(self, trade_date=None):
        day = trade_date or get_effective_trading_date(self.market.lower())
        if not is_market_open(self.market.lower(), day) or not is_market_session_closed(
            self.market.lower(), check_date=day
        ):
            raise ValueError("Market Structure requires a completed trading session")
        codes = get_universe_codes(self.market)
        benchmark = TREND_CONFIG.benchmark_codes[self.market]
        rankings = self.repository.etf_rankings(day)
        if day not in rankings:
            raise ValueError(f"ETF Rotation snapshot is not ready for {day}")
        first_dates = self.repository.first_daily_dates(codes)
        eligible_codes = {code for code in codes if first_dates.get(code) is None or first_dates[code] <= day}
        rows = self.repository.load_daily_history(eligible_codes, day, calendar_lookback_days=self.config.lookback_days)
        histories = defaultdict(dict)
        for row in rows:
            value = row["close"]
            if row["trade_date"] <= day and value is not None and math.isfinite(value) and value > 0:
                histories[row["code"]][row["trade_date"]] = float(value)
        # Align every member to the same exchange sessions: no stale/suspended 5D windows.
        sessions = get_trading_days_between(self.market.lower(), day - timedelta(days=self.config.lookback_days), day)[
            -20:
        ]
        if len(sessions) < 20:
            raise ValueError("Insufficient calendar history")
        ready = {
            code: [histories[code][d] for d in sessions]
            for code in eligible_codes
            if all(d in histories[code] for d in sessions)
        }
        if not eligible_codes or len(ready) / len(eligible_codes) < self.config.minimum_coverage:
            raise ValueError(
                f"Market Structure daily coverage insufficient: {len(ready)}/{len(eligible_codes)} eligible"
            )
        # Benchmark is a calculation-only dependency. db_fresh may supplement its
        # missing DB tail in memory; member readiness above remains strictly DB-only.
        benchmark_result = self.market_data.get_daily_bars(
            [benchmark],
            day - timedelta(days=self.config.lookback_days),
            day,
            adjustment="forward",
            source_policy="db_fresh",
        )
        benchmark_closes = {
            bar.trade_date: float(bar.close)
            for bar in benchmark_result.data.get(benchmark, [])
            if bar.trade_date <= day and bar.close is not None and math.isfinite(bar.close) and bar.close > 0
        }
        if any(d not in benchmark_closes for d in sessions[-6:]):
            raise ValueError(f"Benchmark {benchmark} db_fresh history is incomplete for {day}")
        returns5 = [prices[-1] / prices[-6] - 1 for prices in ready.values()]
        returns1 = [prices[-1] / prices[-2] - 1 for prices in ready.values()]
        benchmark_return = benchmark_closes[day] / benchmark_closes[sessions[-6]] - 1
        metrics = breadth(benchmark_return, returns5)
        metrics.update(
            {
                f"member_above_ma{n}_ratio": sum(p[-1] > fmean(p[-n:]) for p in ready.values()) / len(ready)
                for n in (10, 20)
            }
        )
        metrics.update(rotation_metrics(rankings, day))
        metrics["leadership_concentration_1d"], _ = leadership(returns1, self.config)
        metrics["leadership_concentration_5d"], metrics["leadership_hhi_5d"] = leadership(returns5, self.config)
        payload = {
            "market": self.market,
            "trade_date": day,
            **metrics,
            "metrics_json": {
                "version": self.config.version,
                "universe_key": universe_key(self.market),
                "benchmark_code": benchmark,
                "universe_size": len(eligible_codes),  # Existing clients display this coverage denominator.
                "current_universe_size": len(codes),
                "eligible_universe_size": len(eligible_codes),
                "eligibility_basis": "first_available_stock_daily",
                "member_count": len(ready),
                "data_coverage": len(ready) / len(eligible_codes),
                "states": states(metrics, self.config),
                "rotation_dates": [d.isoformat() for d in sorted(rankings, reverse=True) if d <= day],
                "positive_member_count_5d": sum(r > 0 for r in returns5),
                "top_member_count": math.ceil(len(ready) * self.config.top_fraction),
            },
        }
        self.repository.save(payload)
        return {"status": "completed", "market": self.market, "trade_date": day.isoformat()}

    def backfill(self, start_date: date, end_date: date):
        if start_date > end_date:
            raise ValueError("start_date must not exceed end_date")
        results = []
        for day in get_trading_days_between(self.market.lower(), start_date, end_date):
            results.append(self.run(day))
        return {"status": "completed", "market": self.market, "snapshots": len(results)}


def read_snapshot(market, trade_date=None):
    row = MarketStructureRepository(market).read(trade_date)
    if row is None:
        return None
    return {
        "market": row["market"],
        "trade_date": row["trade_date"],
        "expected_trade_date": get_effective_trading_date(market.lower()),
        "breadth": {k: v for k, v in row.items() if k.startswith(("benchmark_", "median_", "breadth_", "member_"))},
        "rotation": {k: v for k, v in row.items() if k.startswith("rotation_")},
        "leadership": {k: v for k, v in row.items() if k.startswith("leadership_")},
        "metrics": row["metrics_json"],
    }

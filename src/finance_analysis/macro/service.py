"""US macro calculations using only the MarketDataService db_only path."""

from datetime import date
from math import isfinite
from statistics import fmean

from finance_analysis.core.time import utc_now
from finance_analysis.database.repositories.macro import MacroRepository
from finance_analysis.integrations.market_data.service import MarketDataService
from finance_analysis.macro.models import (
    MacroDashboard,
    DataQuality,
    InstrumentMetrics,
    MacroSeries,
    MacroStates,
    Metrics,
    RatioMetrics,
    RiskSignal,
    SeriesPoint,
    MacroSeriesResult,
)
from finance_analysis.macro.config import MACRO_INSTRUMENTS, MACRO_RATIOS, MIN_SIGNAL_COVERAGE, RISK_SIGNALS
from finance_analysis.macro.models import MacroContext, SeriesMode, SeriesRange

History = dict[date, float]


def divide(numerator: History, denominator: History) -> History:
    """Inner join by session date; no forward fill or positional arithmetic."""
    return {
        day: numerator[day] / denominator[day]
        for day in sorted(numerator.keys() & denominator.keys())
        if denominator[day] != 0 and isfinite(numerator[day] / denominator[day])
    }


def metrics(history: History) -> Metrics:
    days = sorted(history)
    if not days:
        return Metrics()
    values = [history[day] for day in days]
    returns = {
        f"ret_{n}d": values[-1] / values[-n - 1] - 1 if len(values) > n and values[-n - 1] else None for n in (1, 5, 20)
    }
    trend = None
    if len(values) >= 20:
        average = fmean(values[-20:])
        trend = "UP" if values[-1] > average else "DOWN" if values[-1] < average else "NEUTRAL"
    return Metrics(trade_date=days[-1], trend=trend, **returns)


def quality(context: MacroContext, histories: dict[str, History], codes: list[str], minimum: int) -> DataQuality:
    missing = [code for code in codes if not histories.get(code) and code not in context.latest_dates]
    stale = [
        code for code in codes if code in context.latest_dates and context.latest_dates[code] != context.trade_date
    ]
    insufficient = [code for code in codes if code not in missing and len(histories.get(code, {})) < minimum]
    available = sum(bool(histories.get(code)) and code not in stale for code in codes)
    return DataQuality(
        expected=len(codes),
        available=available,
        coverage=available / len(codes) if codes else 0,
        missing_symbols=missing,
        stale_symbols=stale,
        insufficient_history_symbols=insufficient,
        partial=bool(missing or stale or insufficient),
    )


class MacroService:
    def __init__(self, repository=None, market_data_service=None):
        self.repository = repository if repository is not None else MacroRepository()
        self.market_data = market_data_service if market_data_service is not None else MarketDataService()

    def _load(self, as_of, window):
        context = self.repository.context(as_of=as_of, window=window)
        if context.trade_date is None or context.start_date is None:
            return context, {}
        result = self.market_data.get_daily_bars(
            list(context.names),
            context.start_date,
            context.trade_date,
            adjustment="forward",
            source_policy="db_only",
        )
        histories = {
            code: {
                bar.trade_date: float(bar.close)
                for bar in bars
                if context.start_date <= bar.trade_date <= context.trade_date and isfinite(bar.close) and bar.close > 0
            }
            for code, bars in result.data.items()
            if code in context.names
        }
        return context, histories

    def dashboard(self, as_of: date | None = None) -> MacroDashboard:
        context, histories = self._load(as_of, 21)
        instruments = []
        all_metrics = {}
        for code, config in MACRO_INSTRUMENTS.items():
            history = histories.get(code, {})
            metric = metrics(history)
            all_metrics[code] = metric
            instruments.append(
                InstrumentMetrics(
                    code=code,
                    name=context.names.get(code) or config.name,
                    category=config.category,
                    close=history.get(metric.trade_date),
                    **metric.model_dump(),
                )
            )
        ratios = []
        for key, config in MACRO_RATIOS.items():
            numerator, denominator = histories.get(config.numerator, {}), histories.get(config.denominator, {})
            history = divide(numerator, denominator)
            metric = metrics(history)
            all_metrics[key] = metric
            fresh = metric.trade_date is not None and metric.trade_date == context.trade_date
            ratios.append(
                RatioMetrics(
                    key=key,
                    name=config.name,
                    value=history.get(metric.trade_date),
                    **metric.model_dump(),
                    signal=self._regime_for_trend(metric.trend) if fresh else None,
                    partial=not fresh or len(history) < 21 or numerator.keys() != denominator.keys(),
                )
            )
        signals = []
        for key, risk_on, weight in RISK_SIGNALS:
            metric = all_metrics[key]
            trend = metric.trend if metric.trade_date == context.trade_date else None
            contribution = (
                None if trend is None else weight * (0.5 if trend == "NEUTRAL" else 1 if trend == risk_on else 0)
            )
            signals.append(
                RiskSignal(
                    key=key,
                    risk_on_trend=risk_on,
                    trend=trend,
                    weight=weight,
                    contribution=contribution,
                )
            )
        supported_weight = sum(signal.weight for signal in signals if signal.contribution is not None)
        signal_coverage = supported_weight / sum(signal.weight for signal in signals)
        score = (
            (sum(signal.contribution for signal in signals if signal.contribution is not None) / supported_weight * 100)
            if signal_coverage >= MIN_SIGNAL_COVERAGE
            else None
        )
        regime = None if score is None else "RISK_ON" if score >= 65 else "RISK_OFF" if score < 35 else "NEUTRAL"

        def state(key, up, down):
            metric = all_metrics[key]
            if metric.trade_date != context.trade_date or metric.trend is None:
                return None
            return up if metric.trend == "UP" else down if metric.trend == "DOWN" else "NEUTRAL"

        data_quality = quality(context, histories, list(MACRO_INSTRUMENTS), 21)
        data_quality.partial |= any(ratio.partial for ratio in ratios)
        return MacroDashboard(
            trade_date=context.trade_date,
            generated_at=utc_now(),
            regime=regime,
            risk_score=score,
            signal_coverage=signal_coverage,
            signals=signals,
            states=MacroStates(
                rates=state("TLT.US", "EASING", "PRESSURE"),
                credit=state("HYG_LQD", "HEALTHY", "WEAK"),
                dollar=state("UUP.US", "STRONG", "WEAK"),
                volatility=state("VIX.US", "ELEVATED", "CALM"),
            ),
            instruments=instruments,
            ratios=ratios,
            data_quality=data_quality,
        )

    @staticmethod
    def _regime_for_trend(trend):
        return {"UP": "RISK_ON", "DOWN": "RISK_OFF", "NEUTRAL": "NEUTRAL", None: None}[trend]

    def series(
        self,
        *,
        range: SeriesRange = "60d",
        mode: SeriesMode = "normalized",
        symbols: list[str] | None = None,
        series: list[str] | None = None,
        benchmark: str = "SPY.US",
        as_of: date | None = None,
    ) -> MacroSeriesResult:
        if range not in ("20d", "60d", "120d", "250d", "ytd") or mode not in ("price", "normalized", "relative"):
            raise ValueError("Unsupported range or mode")
        ratio_keys = list(dict.fromkeys(series or []))
        codes = list(dict.fromkeys(symbols if symbols is not None else [] if ratio_keys else MACRO_INSTRUMENTS))
        if set(codes) - MACRO_INSTRUMENTS.keys() or set(ratio_keys) - MACRO_RATIOS.keys():
            raise ValueError("Only configured US Macro symbols and ratio keys are supported")
        if benchmark not in MACRO_INSTRUMENTS:
            raise ValueError("Benchmark must be a configured US Macro symbol")
        if mode == "relative" and ratio_keys:
            raise ValueError("Ratio series already express relative value; use price or normalized mode")
        context, histories = self._load(as_of, "ytd" if range == "ytd" else int(range[:-1]))
        expected_dates = {day for history in histories.values() for day in history}
        curves = []
        dependencies = list(codes)
        if mode == "relative":
            dependencies.append(benchmark)
        for key in [*codes, *ratio_keys]:
            if key in MACRO_RATIOS:
                config = MACRO_RATIOS[key]
                dependencies.extend([config.numerator, config.denominator])
                left, right = histories.get(config.numerator, {}), histories.get(config.denominator, {})
                history = divide(left, right)
                name, category, code = config.name, "RATIO", None
                incomplete = left.keys() != right.keys()
            else:
                config = MACRO_INSTRUMENTS[key]
                history = histories.get(key, {})
                name, category, code = context.names.get(key) or config.name, config.category, key
                incomplete = False
                if mode == "relative":
                    benchmark_history = histories.get(benchmark, {})
                    incomplete = history.keys() != benchmark_history.keys()
                    history = divide(history, benchmark_history)
            days = sorted(history)
            baseline = history[days[0]] if days else None
            points = [
                SeriesPoint(
                    date=day,
                    value=history[day] if mode == "price" else history[day] / baseline * 100,
                )
                for day in days
                if mode == "price" or baseline
            ]
            curves.append(
                MacroSeries(
                    key=key,
                    code=code,
                    name=name,
                    category=category,
                    points=points,
                    partial=incomplete
                    or not days
                    or days[-1] != context.trade_date
                    or bool(expected_dates - history.keys())
                    or (range != "ytd" and len(days) < int(range[:-1])),
                )
            )
        data_quality = quality(
            context, histories, list(dict.fromkeys(dependencies)), 1 if range == "ytd" else int(range[:-1])
        )
        data_quality.partial |= any(curve.partial for curve in curves)
        return MacroSeriesResult(
            range=range,
            mode=mode,
            benchmark=benchmark if mode == "relative" else None,
            trade_date=context.trade_date,
            series=curves,
            data_quality=data_quality,
        )

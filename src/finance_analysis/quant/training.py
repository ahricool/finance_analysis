"""Training admission uses effective dates, never snapshot readiness alone."""
from __future__ import annotations

from finance_analysis.market_review.trading_calendar import get_market_now
import pandas as pd

from finance_analysis.quant.data import DailyBarLoader
from finance_analysis.quant.markets import get_quant_market_config, get_universe_codes


def validate_training_dates(dates, split=None):
    config = {"train_years": 3, "valid_months": 3, "test_months": 3, "embargo_days": 2, **(split or {})}
    calendar = pd.DatetimeIndex(sorted(set(pd.to_datetime(list(dates)))))
    # Reserve feature warm-up, mature labels and both boundary gaps.
    gap = 5 + int(config["embargo_days"])
    if len(calendar) <= 60 + 5 + 2 * gap:
        raise ValueError("历史不足：训练需要多年有效行情，80交易日推理输入不能用于训练")
    effective = calendar[60:-5]
    train_end = effective[0] + pd.DateOffset(years=int(config["train_years"]))
    train_index = int(effective.searchsorted(train_end, side="right")) - 1
    valid_start = train_index + gap + 1
    if valid_start >= len(effective):
        raise ValueError("有效历史不足以覆盖训练期、验证期、测试期及隔离窗口")
    test_start_target = effective[valid_start] + pd.DateOffset(months=int(config["valid_months"]))
    test_start = int(effective.searchsorted(test_start_target)) + gap
    if test_start >= len(effective):
        raise ValueError("有效历史不足以划分独立测试窗口")
    required_end = effective[test_start] + pd.DateOffset(months=int(config["test_months"]))
    if effective[-1] < required_end - pd.Timedelta(days=7):
        raise ValueError("有效历史不足以覆盖完整测试窗口")
    return {"sessions": len(calendar), "effective_from": str(effective[0].date()),
            "label_cutoff": str(effective[-1].date()), "initial_train_end": str(train_end.date())}


def training_preflight(repository, market, date_from, date_to):
    if date_from >= date_to or date_to > get_market_now(market.lower()).date():
        raise ValueError("请选择有效的历史日期范围")
    config = get_quant_market_config(market)
    codes = get_universe_codes(market)
    loaded = DailyBarLoader(repository).load(market, codes | set(config.benchmark_dependencies), date_from, date_to)
    frame = loaded.frame
    benchmark = frame[frame.instrument == config.label_benchmark]
    if benchmark.empty:
        raise ValueError("训练基准行情缺失，请先完成日线同步")
    result = validate_training_dates(benchmark.datetime)
    calendar = pd.DatetimeIndex(pd.to_datetime(benchmark.datetime)).sort_values().unique()
    mature = calendar[60:-5]
    eligible = []
    for code, group in frame[frame.instrument.isin(codes)].groupby('instrument'):
        stock = group.set_index(pd.to_datetime(group.datetime)).reindex(calendar)
        labels = stock.close.shift(-5) / stock.open.shift(-1) - 1
        if labels.reindex(mature).notna().mean() >= .9:
            eligible.append(code)
    from finance_analysis.quant.config import get_quant_config
    coverage = len(eligible) / len(codes) if codes else 0
    if coverage < get_quant_config().minimum_universe_coverage:
        raise ValueError(f"训练有效标签覆盖不足：{len(eligible)}/{len(codes)}，请补齐历史行情")
    return {**result, "market": market, "universe": config.default_universe,
            "member_count": len(codes), "eligible_count": len(eligible), "coverage": coverage,
            "source_revision": loaded.source_revision,
            "warning": "使用当前证券池回看历史，不代表历史时点可投资成分回测"}

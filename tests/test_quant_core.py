from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from finance_analysis.database.models.quant import QUANT_TABLES
from finance_analysis.quant.events.import_service import EventImportService, calculate_available_at
from finance_analysis.quant.events.scoring import score_events
from finance_analysis.quant.features.daily import add_relative_strength, build_daily_features, build_forward_excess_label
from finance_analysis.quant.intraday_confirmation.service import IntradayConfirmationService
from finance_analysis.quant.models.splits import WalkForwardConfig, walk_forward_splits
from finance_analysis.quant.portfolio.backtest import BacktestCostConfig, run_topk_backtest
from finance_analysis.quant.portfolio.builder import PortfolioBuilder
from finance_analysis.quant.signals.fusion import SignalFusion


def daily_frame(count=90, start="2025-01-01", drift=1.0):
    dates = pd.bdate_range(start, periods=count)
    close = 100 + np.arange(count) * drift
    return pd.DataFrame({"date": dates.date, "open": close - .5, "high": close + 1, "low": close - 1,
                         "close": close, "volume": 1_000 + np.arange(count)})


def test_quant_schema_uses_canonical_market_tables_only():
    names = {model.__tablename__ for model in QUANT_TABLES}
    assert len(names) == 16
    assert not names & {"security_master", "daily_bar", "minute_bar"}
    foreign_keys = {str(fk.target_fullname) for model in QUANT_TABLES for fk in model.__table__.foreign_keys}
    assert "market_data_symbol.id" in foreign_keys


def test_daily_features_are_backward_looking_and_correct():
    bars = daily_frame()
    result = build_daily_features(bars)
    assert result.loc[20, "ret_20d"] == pytest.approx(bars.close.iloc[20] / bars.close.iloc[0] - 1)
    assert result.loc[19, "price_ma20_ratio"] == pytest.approx(bars.close.iloc[19] / bars.close.iloc[:20].mean() - 1)
    assert result.loc[13, "atr_14"] > 0
    changed = bars.copy(); changed.loc[89, "close"] = 9999
    assert build_daily_features(changed).loc[70, "ret_20d"] == result.loc[70, "ret_20d"]


def test_relative_strength_and_forward_label_use_exact_window():
    stock, market, sector = daily_frame(drift=2), daily_frame(drift=1), daily_frame(drift=.5)
    result = add_relative_strength(build_daily_features(stock), market, sector)
    expected = stock.close.iloc[-1] / stock.close.iloc[-21] - market.close.iloc[-1] / market.close.iloc[-21]
    assert result.iloc[-1].relative_20d_to_market == pytest.approx(expected)
    labels = build_forward_excess_label(stock, market, horizon=5)
    expected_label = ((stock.close.iloc[5] / stock.open.iloc[1] - 1) - (market.close.iloc[5] / market.open.iloc[1] - 1)) * 100
    assert labels.iloc[0] == pytest.approx(expected_label)
    assert labels.tail(5).isna().all()


def test_after_hours_event_is_not_available_same_day():
    published = datetime(2026, 7, 3, 20, 10, tzinfo=timezone.utc)  # 16:10 ET
    available = calculate_available_at(published, "US")
    assert available > published
    assert available.weekday() == 0  # July 4/5 weekend -> Monday


def test_event_import_deduplicates_and_vetoes():
    symbol = SimpleNamespace(id=3, market="US", code="NVDA.US")
    stored = {}
    class Repo:
        def upsert_event(self, values):
            if values["dedupe_key"] in stored: return stored[values["dedupe_key"]], False
            row = SimpleNamespace(id=len(stored)+1, **values); stored[values["dedupe_key"]] = row; return row, True
    service = EventImportService(Repo(), SimpleNamespace(get_by_code=lambda code: symbol if code == "NVDA.US" else None))
    item = {"code":"NVDA.US","market":"US","event_type":"regulation","published_at":"2026-07-03T15:00:00-04:00",
            "direction":"negative","importance":1,"confidence":1,"source":"manual","source_event_id":"one","title":"review"}
    assert service.import_json([item])["created"] == 1
    assert service.import_json([item])["duplicates"] == 1
    event = next(iter(stored.values()))
    scored = score_events([event], event.available_at + timedelta(hours=1))
    assert scored["event_score"] < 0
    assert scored["negative_event_veto"]


def test_walk_forward_has_purge_and_embargo_gaps():
    config = WalkForwardConfig(train_years=1, valid_months=2, test_months=2, prediction_horizon=5, embargo_days=3)
    splits = walk_forward_splits(pd.bdate_range("2020-01-01", "2023-01-01"), config)
    assert splits
    first = splits[0]
    assert (pd.Timestamp(first["valid"][0]) - pd.Timestamp(first["train"][1])).days >= 8
    assert first["purge_days"] == 5 and first["embargo_days"] == 3


def test_fusion_gating_and_veto_are_explicit():
    fused = SignalFusion().fuse(.8, .7, .4, "neutral", risk_penalty=.1)
    assert fused.raw_final_score == pytest.approx(.8*.45 + .7*.30 + .4*.25 - .1)
    assert fused.gated_final_score == pytest.approx(fused.raw_final_score * .7)
    strong_sector = SignalFusion().fuse(.8, .7, .4, "neutral", sector_score=.9, risk_penalty=.1)
    weak_sector = SignalFusion().fuse(.8, .7, .4, "neutral", sector_score=.1, risk_penalty=.1)
    assert strong_sector.raw_final_score > weak_sector.raw_final_score
    assert strong_sector.score_components["sector_contribution"] == pytest.approx(.04)
    vetoed = SignalFusion().fuse(.9, .9, .9, "risk_on", negative_event_veto=True)
    assert vetoed.vetoed and vetoed.target_position == 0 and vetoed.signal == "blocked"


def test_portfolio_respects_veto_single_stock_and_sector_caps():
    signals = [{"code":f"S{i}.US","symbol_id":i,"final_score":1-i*.05,"sector_key":"semiconductor","signal":"buy","reasons":[],"vetoed":i==0,"has_sufficient_data":True,"liquidity":2_000_000} for i in range(8)]
    result = PortfolioBuilder().build(signals, .8)
    assert all(item["code"] != "S0.US" or item["action"] == "blocked" for item in result["items"])
    assert all(item["target_weight"] <= .08 for item in result["items"])
    assert sum(item["target_weight"] for item in result["items"] if item["sector_key"] == "semiconductor") <= .30 + 1e-9


def test_backtest_uses_next_open_and_costs():
    bars = pd.DataFrame({"code":["A.US"]*3,"date":pd.date_range("2025-01-01",periods=3).date,"open":[10,20,30],"close":[11,22,33]})
    predictions = pd.DataFrame({"code":["A.US"],"date":[bars.date.iloc[0]],"score":[1.0]})
    benchmark = pd.DataFrame({"date":bars.date,"close":[100,100,100]})
    result = run_topk_backtest(predictions,bars,benchmark,top_k=1,costs=BacktestCostConfig(commission_bps=0,slippage_bps=0))
    assert next(iter(result["daily_returns"].values())) == pytest.approx(22/20-1)


def test_intraday_replay_excludes_bar_at_evaluation_time():
    times = pd.date_range("2026-07-03 13:30", periods=31, freq="min", tz="UTC")
    bars = pd.DataFrame({"bar_time":times,"open":100,"high":101,"low":99,"close":100+np.arange(31)*.01,"volume":100})
    result = IntradayConfirmationService().evaluate("NVDA.US",bars,bars,bars,times[-1])
    assert result["features"]["first_30m_return"] == pytest.approx(bars.close.iloc[29]/100-1)
    changed=bars.copy(); changed.loc[30,"close"]=9999
    assert IntradayConfirmationService().evaluate("NVDA.US",changed,changed,changed,times[-1])["features"]["price"] != 9999

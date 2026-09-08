from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from finance_analysis.database.models.quant import QUANT_TABLES
from finance_analysis.quant.portfolio.builder import PortfolioBuilder
from finance_analysis.quant.regime.service import MarketRegimeService
from finance_analysis.quant.signals.fusion import SignalFusion


def daily_frame(count=90, start="2025-01-01", drift=1.0):
    dates = pd.bdate_range(start, periods=count)
    close = 100 + np.arange(count) * drift
    return pd.DataFrame(
        {
            "date": dates.date,
            "open": close - 0.5,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 1_000 + np.arange(count),
        }
    )


def test_quant_schema_uses_canonical_market_tables_only():
    names = {model.__tablename__ for model in QUANT_TABLES}
    assert len(names) == 8
    assert not names & {"security_master", "daily_bar", "minute_bar"}
    foreign_keys = {str(fk.target_fullname) for model in QUANT_TABLES for fk in model.__table__.foreign_keys}
    assert "instrument.id" in foreign_keys
    assert "universe.id" in foreign_keys

def test_market_regime_uses_primary_relative_to_broad_without_risk_benchmark():
    primary = daily_frame(drift=2.0)
    broad = daily_frame(drift=1.0)

    result = MarketRegimeService().calculate(
        primary,
        broad,
        {"A.US": primary},
        benchmark_labels=("QQQ.US", "SPY.US"),
    )

    expected_relative = primary.close.iloc[-1] / primary.close.iloc[-21] - broad.close.iloc[-1] / broad.close.iloc[-21]
    assert result.features["primary_benchmark"] == "QQQ.US"
    assert result.features["broad_benchmark"] == "SPY.US"
    assert result.features["primary_relative_broad_20d"] == pytest.approx(expected_relative)
    assert "risk_benchmark" not in result.features
    assert json.loads(json.dumps(result.features))["universe_20d_high_count"] == 1


def test_cn_market_regime_score_uses_csi300_trend_and_growth_style() -> None:
    csi300 = daily_frame(drift=0.5)
    growth = daily_frame(drift=1.5)
    members = {
        "600519.SH": daily_frame(drift=0.8),
        "000001.SZ": daily_frame(drift=-0.1),
    }

    result = MarketRegimeService().calculate(
        csi300,
        csi300,
        members,
        benchmark_labels=("510300.SH", "510300.SH"),
        style=growth,
        style_label="159915.SZ",
    )

    assert result.features["primary_benchmark"] == "510300.SH"
    assert result.features["style_benchmark"] == "159915.SZ"
    assert result.features["style_relative_broad_20d"] > 0
    breakdown = result.features["score_breakdown"]
    components = [component for group in breakdown["groups"] for component in group["components"]]
    assert {component["key"] for component in components} == {
        "trend_ma20",
        "trend_ma60",
        "momentum_20d",
        "breadth_up",
        "breadth_ma20",
        "breadth_ma60",
        "realized_volatility_20d",
        "max_drawdown_60d",
        "style_relative_20d",
    }
    assert sum(component["weight"] for component in components) == pytest.approx(1.0)
    assert sum(component["contribution"] for component in components) == pytest.approx(result.market_score)
    assert breakdown["score"] == pytest.approx(result.market_score)
    assert 0 <= result.market_score <= 1


def test_market_score_to_exposure_is_continuous_around_regime_thresholds() -> None:
    service = MarketRegimeService()

    assert service.max_equity_exposure(0) == pytest.approx(0.10)
    assert service.max_equity_exposure(1) == pytest.approx(0.80)
    assert service.max_equity_exposure(0.3499) < service.max_equity_exposure(0.3501)
    assert service.max_equity_exposure(0.6499) < service.max_equity_exposure(0.6501)
    assert service.max_equity_exposure(0.3501) - service.max_equity_exposure(0.3499) < 0.001
    assert service.max_equity_exposure(0.6501) - service.max_equity_exposure(0.6499) < 0.001


def test_us_market_regime_keeps_qqq_spy_contract_and_returns_valid_breakdown() -> None:
    qqq = daily_frame(drift=2.0)
    spy = daily_frame(drift=1.0)

    result = MarketRegimeService().calculate(
        qqq,
        spy,
        {"AAPL.US": qqq},
        benchmark_labels=("QQQ.US", "SPY.US"),
        style=qqq,
        style_label="QQQ.US",
    )

    assert result.features["primary_benchmark"] == "QQQ.US"
    assert result.features["broad_benchmark"] == "SPY.US"
    assert result.features["style_relative_broad_20d"] > 0
    assert result.regime in {"risk_on", "neutral", "risk_off"}
    assert 0 <= result.market_score <= 1
    assert 0.10 <= result.max_equity_exposure <= 0.80


def test_fusion_gating_and_risk_penalty_are_explicit():
    fused = SignalFusion().fuse(0.8, 0.7, "neutral", risk_penalty=0.1)
    expected_pre_regime = 0.8 * 0.60 + 0.7 * 0.40 - 0.1
    assert fused.final_score == pytest.approx(expected_pre_regime * 0.7)
    assert fused.score_components["pre_regime_score"] == pytest.approx(expected_pre_regime)
    assert fused.score_components["regime_multiplier"] == pytest.approx(0.7)


def test_portfolio_is_a_ranked_target_allocation_with_single_stock_caps():
    signals = [
        {
            "code": f"S{i}.US",
            "instrument_id": i,
            "final_score": 1 - i * 0.05,
            "signal": "buy",
            "reasons": [],
            "has_sufficient_data": True,
            "liquidity": 2_000_000,
        }
        for i in range(8)
    ]
    result = PortfolioBuilder().build(signals, 0.8)
    assert [item["rank"] for item in result["items"]] == [1, 2, 3, 4, 5]
    assert all(item["target_weight"] <= 0.08 for item in result["items"])
    assert result["target_equity_exposure"] == pytest.approx(0.4)
    assert all("current_weight" not in item and "action" not in item for item in result["items"])

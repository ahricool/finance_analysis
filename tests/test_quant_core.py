from __future__ import annotations

from datetime import date

import json

import numpy as np
import pandas as pd
import pytest

from finance_analysis.database.models.quant import QUANT_TABLES  # pragma: allowlist secret
from finance_analysis.quant.lookback import PREDICTION_FEATURE_LOOKBACK_SESSIONS, prediction_dataset_start  # pragma: allowlist secret
from finance_analysis.quant.portfolio.builder import PortfolioBuilder  # pragma: allowlist secret
from finance_analysis.quant.regime.service import MarketRegimeService  # pragma: allowlist secret
from finance_analysis.quant.signals.fusion import SignalFusion  # pragma: allowlist secret
from finance_analysis.quant.targets import production_target_config, stored_target_matches_production  # pragma: allowlist secret


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


def test_fusion_does_not_multiply_alpha_by_regime():
    fused = SignalFusion().fuse(0.8, 0.7, "neutral", market_score=0.5, risk_penalty=0.1)
    expected = 0.8 * 0.60 + 0.7 * 0.40 - 0.1
    assert fused.final_score == pytest.approx(expected)
    assert fused.score_components["market_regime"] == "neutral"
    assert fused.score_components["market_score"] == pytest.approx(0.5)
    assert "regime_multiplier" not in fused.score_components
    assert "pre_regime_score" not in fused.score_components
    risk_off = SignalFusion().fuse(0.8, 0.7, "risk_off", market_score=0.2, risk_penalty=0.1)
    assert risk_off.final_score == pytest.approx(expected)


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
    assert [item["rank"] for item in result["items"]] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert all(item["target_weight"] <= 0.08 for item in result["items"])
    assert result["target_equity_exposure"] == pytest.approx(0.64)
    assert "exceeds 8 × 8% single-stock cap" in result["warnings"][0]
    assert all("current_weight" not in item and "action" not in item for item in result["items"])
    assert all(
        item["constraints"]["limits"]["single_stock_max_weight"] == 0.08
        and item["constraints"]["limits"]["max_equity_exposure"] == 0.8
        and item["constraints"]["limits"]["selected_count"] == 8
        for item in result["items"]
    )


def _buy_signals(count: int) -> list[dict]:
    return [
        {
            "code": f"S{i}.US",
            "instrument_id": i,
            "final_score": 1 - i * 0.01,
            "signal": "buy",
            "reasons": [],
            "has_sufficient_data": True,
            "liquidity": 2_000_000,
        }
        for i in range(count)
    ]


def test_cross_section_and_time_series_targets_are_model_owned() -> None:
    cs = production_target_config("cross_section_lgbm")
    ts = production_target_config("time_series_lgbm")
    assert cs["prediction_horizon"] == ts["prediction_horizon"] == 5
    assert cs["entry_price"] == ts["entry_price"] == "open"
    assert cs["exit_price"] == ts["exit_price"] == "close"
    assert cs == {"prediction_horizon": 5, "entry_price": "open", "exit_price": "close", "benchmark": "market", "excess_return": True}
    assert ts["benchmark"] == "none"
    assert ts["excess_return"] is False
    assert stored_target_matches_production("cross_section_lgbm", None)
    assert stored_target_matches_production("cross_section_lgbm", {})
    assert not stored_target_matches_production("time_series_lgbm", None)
    assert not stored_target_matches_production("time_series_lgbm", {"benchmark": "market", "excess_return": True})
    assert stored_target_matches_production("time_series_lgbm", ts)
    assert not stored_target_matches_production("cross_section_lgbm", {**cs, "prediction_horizon": 10})
    assert not stored_target_matches_production("time_series_lgbm", {**ts, "prediction_horizon": 10})
    assert not stored_target_matches_production("cross_section_lgbm", {**cs, "entry_price": "close"})


def test_portfolio_reaches_regime_exposure_without_breaking_single_stock_cap() -> None:
    builder = PortfolioBuilder()
    risk_on = builder.build(_buy_signals(20), 0.80)
    neutral = builder.build(_buy_signals(20), 0.40)
    risk_off = builder.build(_buy_signals(20), 0.10)

    assert len(risk_on["items"]) == 10
    assert all(item["target_weight"] == pytest.approx(0.08) for item in risk_on["items"])
    assert risk_on["target_equity_exposure"] == pytest.approx(0.80)

    assert len(neutral["items"]) == 5
    assert all(item["target_weight"] == pytest.approx(0.08) for item in neutral["items"])
    assert neutral["target_equity_exposure"] == pytest.approx(0.40)

    assert len(risk_off["items"]) == 5
    assert all(item["target_weight"] == pytest.approx(0.02) for item in risk_off["items"])
    assert risk_off["target_equity_exposure"] == pytest.approx(0.10)
    assert all(item["target_weight"] <= 0.08 for item in [*risk_on["items"], *neutral["items"], *risk_off["items"]])


def test_prediction_dataset_lookback_uses_trading_sessions() -> None:
    from finance_analysis.market_review.trading_calendar import get_trading_days_between  # pragma: allowlist secret

    trade_date = date(2026, 7, 16)
    start = prediction_dataset_start("US", trade_date)
    sessions = [item for item in get_trading_days_between("us", start, trade_date) if item <= trade_date]
    assert PREDICTION_FEATURE_LOOKBACK_SESSIONS == 80
    assert len(sessions) == PREDICTION_FEATURE_LOOKBACK_SESSIONS
    assert start < trade_date
    assert sessions[-1] == trade_date
    assert (trade_date - start).days < 500

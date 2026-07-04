from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

import pytest

from finance_analysis.backtest.engines.registry import create_engine, get_engine_definitions
from finance_analysis.backtest.engines.rqalpha_data_source import PostgreSQLRQAlphaDataSource
from finance_analysis.backtest.market_rules import MarketRuleRegistry
from finance_analysis.backtest.strategies.registry import get_strategy, list_strategies
from finance_analysis.backtest.types import BacktestRequest, DailyBar


def synthetic_request(engine: str, *, market: str = "CN") -> BacktestRequest:
    closes = [10, 10, 10, 9, 8, 12, 13, 12, 7, 6, 11, 12]
    start = date(2025, 1, 2)
    code = "600519.SH" if market == "CN" else "AAPL.US"
    bars = tuple(
        DailyBar(
            trading_date=start + timedelta(days=index),
            open=close + 0.25,
            high=close + 0.5,
            low=close - 0.5,
            close=close,
            volume=100_000,
            limit_up=close * 1.1 if market == "CN" else None,
            limit_down=close * 0.9 if market == "CN" else None,
        )
        for index, close in enumerate(closes)
    )
    return BacktestRequest(
        engine=engine,
        strategy_key="sma_cross",
        market=market,
        code=code,
        symbol_id=1,
        start_date=bars[3].trading_date,
        end_date=bars[-1].trading_date,
        initial_cash=100_000,
        parameters={"fast_window": 2, "slow_window": 3},
        bars=bars,
        commission_rate=0,
        stamp_tax_rate=0,
        transfer_fee_rate=0,
    )


def test_engine_registry_is_ordered_and_reports_versions():
    engines = get_engine_definitions()
    assert [item.key for item in engines] == ["backtrader", "rqalpha"]
    assert engines[0].is_default is True
    assert engines[0].recommended is True
    assert engines[0].version == "1.9.78.123"
    assert engines[1].version == "6.2.0"
    assert engines[1].supported_markets == ("CN",)
    assert "US" not in engines[1].supported_markets


def test_unavailable_engine_includes_reason(monkeypatch):
    from finance_analysis.backtest.engines import registry

    monkeypatch.setattr(registry, "_availability", lambda package: (False, f"{package} import failed", None))
    assert all(not item.available and item.unavailable_reason for item in registry.get_engine_definitions())


def test_strategy_registry_and_dynamic_parameter_validation():
    strategy = get_strategy("sma_cross")
    assert strategy in list_strategies(engine="backtrader", market="US")
    assert strategy in list_strategies(engine="rqalpha", market="CN")
    assert strategy.validate_parameters({}) == {"fast_window": 5, "slow_window": 20}
    with pytest.raises(ValueError, match="less than"):
        strategy.validate_parameters({"fast_window": 20, "slow_window": 20})
    with pytest.raises(ValueError, match="between"):
        strategy.validate_parameters({"fast_window": 1, "slow_window": 20})


def test_market_rules_cover_t_plus_lots_and_fees():
    us = MarketRuleRegistry.get("US")
    cn = MarketRuleRegistry.get("CN")
    acquired = date(2025, 1, 2)
    assert us.can_sell(acquired_date=acquired, trading_date=acquired)
    assert not cn.can_sell(acquired_date=acquired, trading_date=acquired)
    assert cn.can_sell(acquired_date=acquired, trading_date=date(2025, 1, 3))
    assert us.normalize_buy_quantity(123.9, acquired) == 123
    assert cn.normalize_buy_quantity(1239, acquired) == 1200
    assert not cn.can_fill(side="buy", open_price=11, limit_up=11, limit_down=9, suspended=False)
    assert not cn.can_fill(side="sell", open_price=9, limit_up=11, limit_down=9, suspended=False)
    assert cn.can_fill(side="buy", open_price=10, limit_up=11, limit_down=9, suspended=False)
    fees = cn.calculate_fees(
        side="sell", gross_amount=10_000, commission_rate=0.0008,
        stamp_tax_rate=0.001, transfer_fee_rate=0.00001,
    )
    assert fees.commission == 8
    assert fees.tax == 10
    assert fees.other_fee == 0.1
    with pytest.raises(ValueError, match="lot size"):
        MarketRuleRegistry.get("HK").lot_size(acquired)


def test_backtrader_uses_next_open_and_standardizes_results():
    request = synthetic_request("backtrader")
    result = create_engine("backtrader").run(request)
    assert result.engine == "backtrader"
    assert [(trade.side, trade.signal_date, trade.trade_date, trade.price) for trade in result.trades] == [
        ("buy", request.bars[5].trading_date, request.bars[6].trading_date, request.bars[6].open),
        ("sell", request.bars[8].trading_date, request.bars[9].trading_date, request.bars[9].open),
        ("buy", request.bars[10].trading_date, request.bars[11].trading_date, request.bars[11].open),
    ]
    assert result.trades[0].price != request.bars[5].close
    assert len(result.equity_curve) == sum(bar.trading_date >= request.start_date for bar in request.bars)


def test_rqalpha_uses_custom_data_source_and_next_open():
    request = synthetic_request("rqalpha")
    source = PostgreSQLRQAlphaDataSource(request)
    assert list(source.get_instruments())[0].order_book_id == request.code
    assert source.available_data_range("1d") == (request.bars[0].trading_date, request.bars[-1].trading_date)
    result = create_engine("rqalpha").run(request)
    assert result.engine == "rqalpha"
    assert result.engine_debug["bundle_download"] is False
    assert [(trade.signal_date, trade.trade_date, trade.price) for trade in result.trades] == [
        (request.bars[5].trading_date, request.bars[6].trading_date, request.bars[6].open),
        (request.bars[8].trading_date, request.bars[9].trading_date, request.bars[9].open),
        (request.bars[10].trading_date, request.bars[11].trading_date, request.bars[11].open),
    ]


def test_cross_engine_trade_and_final_equity_consistency():
    backtrader = create_engine("backtrader").run(synthetic_request("backtrader"))
    rqalpha = create_engine("rqalpha").run(synthetic_request("rqalpha"))
    bt_fills = [(t.side, t.signal_date, t.trade_date, t.price, t.quantity) for t in backtrader.trades]
    rq_fills = [(t.side, t.signal_date, t.trade_date, t.price, t.quantity) for t in rqalpha.trades]
    assert bt_fills == rq_fills
    assert backtrader.summary["trade_count"] == rqalpha.summary["trade_count"]
    assert backtrader.summary["final_equity"] == pytest.approx(rqalpha.summary["final_equity"], abs=0.01)


def test_cross_engine_fee_model_consistency():
    backtrader_request = replace(
        synthetic_request("backtrader"),
        commission_rate=0.0008,
        stamp_tax_rate=0.0005,
        transfer_fee_rate=0.00001,
    )
    rqalpha_request = replace(backtrader_request, engine="rqalpha")
    backtrader = create_engine("backtrader").run(backtrader_request)
    rqalpha = create_engine("rqalpha").run(rqalpha_request)
    assert [trade.total_fee for trade in backtrader.trades] == pytest.approx(
        [trade.total_fee for trade in rqalpha.trades], abs=0.000001
    )
    assert backtrader.summary["final_equity"] == pytest.approx(rqalpha.summary["final_equity"], abs=0.01)


def test_selected_engine_failure_is_not_silently_replaced(monkeypatch):
    from finance_analysis.backtest.engines import registry

    class BrokenRQAlpha:
        engine_key = "rqalpha"

        def run(self, request):
            raise RuntimeError("rqalpha failed")

    monkeypatch.setattr(registry, "create_engine", lambda key: BrokenRQAlpha())
    with pytest.raises(RuntimeError, match="rqalpha failed"):
        registry.create_engine("rqalpha").run(synthetic_request("rqalpha"))

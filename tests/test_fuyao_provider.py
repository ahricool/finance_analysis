"""Offline contract tests for the five-source market-data boundary."""

from datetime import date, datetime, timedelta, timezone

import httpx
import pytest

from finance_analysis.integrations.market_data.config import DataProviderConfig, provider_order
from finance_analysis.integrations.market_data.fundamental_adapter import FuyaoFundamentalAdapter
from finance_analysis.integrations.market_data.models import (
    Adjustment,
    DailyBarsRequest,
    InstrumentRequest,
    Market,
    QuoteRequest,
)
from finance_analysis.integrations.market_data.providers.fuyao import FuyaoError, FuyaoProvider, date_ms
from finance_analysis.integrations.market_data.registry import (
    DAILY_BARS,
    MINUTE_BARS,
    REALTIME_QUOTES,
    LATEST_MARKET_SNAPSHOT,
    MARKET_INDICES,
    MARKET_STATS,
    SECTOR_RANKINGS,
    INSTRUMENT_INFO,
    ProviderConfigurationError,
    ProviderRegistry,
)
from finance_analysis.integrations.market_data.service import MarketDataService, build_default_registry

SYMBOL = "600519.SH"
DAY = date(2026, 9, 15)


def snapshot(symbol=SYMBOL, change=1.5):
    return {
        "thscode": symbol,
        "last_price": 10.5,
        "price_change": 0.5,
        "price_change_ratio_pct": change,
        "open_price": 10,
        "high_price": 11,
        "low_price": 9,
        "prev_price": 10,
        "volume": 1234,
        "turnover": 12345,
    }


def provider(handler):
    calls = []

    def transport(request):
        calls.append(request)
        assert request.headers["X-api-key"] == "test-key"
        value = handler(request.url.path, dict(request.url.params))
        if isinstance(value, httpx.Response):
            return value
        return httpx.Response(200, json={"code": 0, "data": value})

    p = FuyaoProvider(api_key="test-key", transport=httpx.MockTransport(transport))
    from time import monotonic

    p._asset_types.update({s: (monotonic(), "a-share") for s in (SYMBOL, "000001.SZ")})
    return p, calls


def test_registry_exact_external_inventory_internal_readers_and_order():
    registry = build_default_registry(DataProviderConfig())
    assert set(registry.names()) == {"tickflow", "yfinance", "longbridge", "fuyao", "easyquotation"}
    assert set(registry.names(include_internal=True)) - set(registry.names()) == {"database", "streaming"}
    assert registry.capabilities("fuyao") == {
        DAILY_BARS,
        REALTIME_QUOTES,
        LATEST_MARKET_SNAPSHOT,
        MARKET_INDICES,
        MARKET_STATS,
        SECTOR_RANKINGS,
        INSTRUMENT_INFO,
    }
    assert registry.capabilities("easyquotation") == {LATEST_MARKET_SNAPSHOT}
    with pytest.raises(ProviderConfigurationError, match="do not support"):
        registry.resolve(["fuyao"], MINUTE_BARS)
    assert provider_order("CN", DAILY_BARS) == ("tickflow", "fuyao", "yfinance")
    assert provider_order("CN", MINUTE_BARS) == ("streaming", "longbridge")
    assert provider_order("CN", REALTIME_QUOTES) == ("streaming", "longbridge", "fuyao")
    for capability in (LATEST_MARKET_SNAPSHOT, MARKET_INDICES, MARKET_STATS, SECTOR_RANKINGS):
        assert provider_order("CN", capability) == ("fuyao",)
    assert provider_order("CN", INSTRUMENT_INFO) == ("database", "tickflow", "longbridge", "fuyao", "yfinance")
    for market in ("US", "HK"):
        assert provider_order(market, DAILY_BARS) == (
            ("yfinance", "tickflow") if market == "US" else ("longbridge", "yfinance")
        )
        assert provider_order(market, MINUTE_BARS) == (
            ("streaming", "longbridge", "yfinance") if market == "US" else ("streaming", "longbridge")
        )
        assert provider_order(market, REALTIME_QUOTES) == ("streaming", "longbridge", "yfinance")
        assert provider_order(market, MARKET_INDICES) == ("longbridge", "yfinance")
        assert provider_order(market, INSTRUMENT_INFO) == ("database", "tickflow", "longbridge", "yfinance")


def test_forward_daily_units_dates_validation_and_partial_failure():
    def handler(path, params):
        if params["thscode"] == "000001.SZ":
            return httpx.Response(200, json={"code": 5002, "data": None})
        assert params["adjust"] == "forward"
        assert params["interval"] == "1d"
        assert int(params["start"]) == date_ms(DAY)
        return {
            "item": [
                {
                    "date_ms": date_ms(DAY),
                    "open_price": 10,
                    "high_price": 11,
                    "low_price": 9,
                    "close_price": 10.5,
                    "volume": 1234,
                    "turnover": 12345,
                }
            ]
        }

    p, _ = provider(handler)
    result = p.fetch_daily_bars(DailyBarsRequest((SYMBOL, "000001.SZ"), DAY, DAY, Adjustment.FORWARD))
    bar = result.data[SYMBOL][0]
    assert (bar.volume, bar.amount, bar.trade_date, bar.bar_time) == (1234, 12345, DAY, None)
    assert bar.adjustment == Adjustment.FORWARD
    assert "000001.SZ" in result.request_errors
    with pytest.raises(ValueError, match="forward"):
        p.fetch_daily_bars(DailyBarsRequest((SYMBOL,), DAY, DAY, Adjustment.RAW))


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(429),
        httpx.Response(503),
        httpx.Response(200, json={"code": 4001, "data": None}),
        httpx.Response(200, json={"code": 2001, "data": None}),
        httpx.Response(200, json={"code": 0, "data": None}),
    ],
)
def test_http_and_envelope_errors_do_not_retry_or_leak_key(response):
    p, calls = provider(lambda path, params: response)
    result = p.fetch_quotes(QuoteRequest((SYMBOL,)))
    assert SYMBOL in result.failed_symbols
    assert "test-key" not in result.failed_symbols[SYMBOL]
    assert len(calls) == 1
    assert "test-key" not in repr(DataProviderConfig(fuyao_api_key="test-key"))


def test_daily_router_falls_through_and_keeps_sticky_failure():
    p, _ = provider(lambda path, params: httpx.Response(200, json={"code": 5003}))
    valid, _ = provider(
        lambda path, params: {
            "item": [
                {
                    "date_ms": date_ms(DAY),
                    "open_price": 10,
                    "high_price": 11,
                    "low_price": 9,
                    "close_price": 10.5,
                    "volume": 1234,
                }
            ]
        }
    )
    registry = ProviderRegistry()
    registry.register("fuyao", p, capabilities={DAILY_BARS})
    registry.register("yfinance", valid, capabilities={DAILY_BARS})
    result = MarketDataService(registry).get_daily_bars(
        [SYMBOL], DAY, DAY, adjustment="forward", source_policy="remote_only"
    )
    assert result.providers_used[SYMBOL] == "yfinance"
    assert SYMBOL in result.request_errors


def test_quotes_and_instruments_are_canonical_and_reject_cross_market():
    p, _ = provider(
        lambda path, params: {
            "timestamp": date_ms(DAY),
            "item": (
                [{"thscode": SYMBOL, "name": "贵州茅台", "asset_type": "a-share"}]
                if path.endswith("search")
                else [snapshot()]
            ),
        }
    )
    quote = p.fetch_quotes(QuoteRequest((SYMBOL,))).data[SYMBOL]
    assert quote.volume == 1234 and quote.amount == 12345
    assert quote.change_pct == 1.5 and quote.quote_time.tzinfo == timezone.utc
    assert "thscode" not in quote.to_dict()
    info = p.get_instrument_info(InstrumentRequest((SYMBOL,))).data[SYMBOL]
    assert info.name == "贵州茅台" and info.instrument_type == "stock"
    with pytest.raises(ValueError, match="CN only"):
        p.fetch_quotes(QuoteRequest(("AAPL.US",)))


def overview_handler(path, params):
    if path.endswith("tickers/list"):
        return {"item": [{"thscode": SYMBOL, "name": "贵州茅台"}], "total": 1}
    if path.endswith("ths-index-list"):
        return {
            "item": [
                {
                    "thscode": "881101.TI" if params["tag"] == "industry" else "886042.TI",
                    "name": "行业" if params["tag"] == "industry" else "概念",
                }
            ]
        }
    if "limit-" in path:
        assert int(params["date_ms"]) == date_ms(DAY)
        return {"pagination": {"total": 5 if "limit-up" in path else 2}}
    if "a-share-index" in path:
        return {
            "timestamp": date_ms(DAY),
            "item": [snapshot(s, i - 1) for i, s in enumerate(params["thscodes"].split(","))],
        }
    return {"timestamp": date_ms(DAY), "total": 1, "item": [snapshot()]}


def test_cn_overviews_through_service_use_fuyao():
    p, _ = provider(overview_handler)
    registry = build_default_registry()
    registry.get("fuyao").provider._api_key = "test-key"
    registry.get("fuyao").provider._transport = p._transport
    service = MarketDataService(registry)
    quote = service.get_market_snapshot("CN").data[SYMBOL]
    assert quote.name == "贵州茅台" and quote.provider == "fuyao"
    assert len(service.get_market_indices("CN")) == 6
    stats = service.get_market_stats("CN")
    assert (stats.up_count, stats.down_count, stats.flat_count) == (1, 0, 0)
    assert (stats.limit_up_count, stats.limit_down_count, stats.total_amount) == (5, 2, 12345)
    ranks = service.get_sector_rankings("CN")
    assert ranks.top[0]["name"] == "概念" and ranks.bottom[0]["name"] == "行业"


def test_snapshot_pagination_uses_directory_offsets_even_when_quotes_missing():
    offsets = []

    def handler(path, params):
        if "tickers/list" in path:
            return {"item": [], "total": 0}
        offsets.append(int(params["offset"]))
        return {
            "timestamp": date_ms(DAY),
            "total": 1001,
            "item": [snapshot(SYMBOL if params["offset"] == "0" else "000001.SZ")],
        }

    p, _ = provider(handler)
    result = p.fetch_market_snapshot(Market.CN)
    assert offsets == [0, 1000]
    assert len(result.data) == 2
    assert "CN" in result.failed_symbols
    with pytest.raises(FuyaoError, match="incomplete"):
        p.get_market_stats(Market.CN)


def test_partial_sector_snapshot_and_limit_failure_fail_open():
    def handler(path, params):
        if "limit-up-pool" in path:
            return httpx.Response(200, json={"code": 5002})
        return overview_handler(path, params)

    p, _ = provider(handler)
    registry = ProviderRegistry()
    registry.register("fuyao", p, capabilities={MARKET_STATS})
    assert MarketDataService(registry).get_market_stats("CN") is None


def financial_handler(path, params):
    period = date_ms(date(2026, 6, 30))
    if path.endswith("income-statements"):
        return {
            "item": [
                {
                    "thscode": SYMBOL,
                    "period_end_ms": period,
                    "report_date_ms": date_ms(date(2026, 8, 15)),
                    "operating_income": 100,
                    "parent_holder_net_profit": 20,
                    "net_profit": 22,
                }
            ]
        }
    if path.endswith("cash-flow-statements"):
        return {
            "item": [
                {
                    "thscode": SYMBOL,
                    "period_end_ms": period,
                    "report_date_ms": date_ms(date(2026, 8, 16)),
                    "act_cash_flow_net": 30,
                }
            ]
        }
    if path.endswith("balance-sheets"):
        return {"item": []}
    if path.endswith("indicators"):
        assert params["report"] == "2026-2"  # Disclosure in Q3 is not the fiscal quarter.
        return {
            "abilities": [
                {
                    "indicators": [
                        {"index_id": key, "value": value}
                        for key, value in [
                            ("operating_income_yoy_growth_ratio", "15"),
                            ("net_profit_yoy_growth_ratio", "20"),
                            ("index_weighted_avg_roe", "12.5"),
                            ("sale_gross_margin", "35.5"),
                        ]
                    ]
                }
            ]
        }
    if path.endswith("valuations/snapshot"):
        return {"item": [{"thscode": SYMBOL, "pe_ttm": 20, "pe_mrq": 21, "pb_mrq": 3, "ps_ttm": 4, "pcf_ttm": -5}]}
    return {"thscode": SYMBOL, "item": [{"ex_date_ms": date_ms(DAY), "dividend_per_share": 2, "per_share_bonus": 0}]}


def test_fundamentals_normalize_values_and_align_fiscal_periods():
    p, _ = provider(financial_handler)
    bundle = FuyaoFundamentalAdapter(p).get_fundamental_bundle(SYMBOL)
    report = bundle["earnings"]["financial_report"]
    assert report["report_date"] == "2026-06-30"
    assert report["announcement_date"] == "2026-08-16"
    assert (report["revenue"], report["net_profit_parent"], report["operating_cash_flow"]) == (100, 20, 30)
    assert bundle["growth"] == {"revenue_yoy": 15, "net_profit_yoy": 20, "roe": 12.5, "gross_margin": 35.5}
    assert bundle["valuation"]["pcf_ttm"] == -5
    assert bundle["valuation"]["pe_mrq"] == 21
    assert bundle["earnings"]["dividend"]["events"][0]["cash_dividend_per_share"] == 2
    assert not bundle["institution"]
    assert "forecast_summary" not in bundle["earnings"]


def test_missing_cash_flow_and_malformed_indicators_preserve_other_fundamentals():
    def handler(path, params):
        if path.endswith("cash-flow-statements"):
            return httpx.Response(200, json={"code": 5002})
        if path.endswith("indicators"):
            return {"abilities": None}
        return financial_handler(path, params)

    p, _ = provider(handler)
    bundle = FuyaoFundamentalAdapter(p).get_fundamental_bundle(SYMBOL)
    assert bundle["earnings"]["financial_report"]["revenue"] == 100
    assert bundle["valuation"]["pe_ratio"] == 20
    assert bundle["status"] == "partial" and len(bundle["errors"]) == 2
    registry = ProviderRegistry()
    registry.register("fuyao", p, capabilities=set())
    context = MarketDataService(registry).get_fundamental_context(SYMBOL)
    assert context["status"] == "partial"
    assert context["earnings"]["data"]["financial_report"]["revenue"] == 100
    assert context["institution"]["status"] == context["capital_flow"]["status"] == "not_supported"


def test_wrong_cash_flow_quarter_is_not_merged_with_latest_report():
    def handler(path, params):
        data = financial_handler(path, params)
        if path.endswith("cash-flow-statements"):
            data["item"][0]["period_end_ms"] = date_ms(date(2026, 3, 31))
        return data

    p, _ = provider(handler)
    report = FuyaoFundamentalAdapter(p).get_fundamental_bundle(SYMBOL)["earnings"]["financial_report"]
    assert "operating_cash_flow" not in report


@pytest.mark.parametrize(
    "symbol,kind,path",
    [
        ("510300.SH", "fund-etf", "/api/fund/market/historical"),
        ("000300.SH", "a-share-index", "/api/a-share-index/prices/historical"),
    ],
)
def test_daily_selects_official_asset_endpoint_and_keeps_forward_contract(symbol, kind, path):
    def handler(endpoint, params):
        if endpoint.endswith("search"):
            return {"item": [{"thscode": symbol, "asset_type": kind}]}
        assert endpoint == path and "adjust" not in params
        return {
            "adjust": None,
            "thscode": symbol,
            "interval": "1d",
            "item": [
                {
                    "date_ms": date_ms(DAY),
                    "open_price": 10,
                    "high_price": 11,
                    "low_price": 9,
                    "close_price": 10.5,
                    "volume": 100,
                    "turnover": 1000,
                }
            ],
        }

    p, calls = provider(handler)
    result = p.fetch_daily_bars(DailyBarsRequest((symbol,), DAY, DAY, Adjustment.FORWARD))
    assert result.data[symbol][0].adjustment == Adjustment.FORWARD
    assert len(calls) == 2


def test_suspended_and_unavailable_rows_are_excluded_not_counted_flat():
    def handler(path, params):
        data = overview_handler(path, params)
        if path == "/api/a-share/prices/snapshot":
            data["item"].append({"thscode": "000001.SZ", "last_price": None, "volume": 0, "turnover": 0})
            data["total"] = 2
        return data

    p, _ = provider(handler)
    stats = p.get_market_stats(Market.CN)
    assert stats.up_count == 1 and stats.flat_count == 0 and stats.total_amount == 12345


def test_live_calculated_growth_ids_are_normalized_without_raw_payload():
    def handler(path, params):
        if path.endswith("indicators"):
            return {
                "abilities": [
                    {
                        "indicators": [
                            {"index_id": "calculate_operating_income_yoy_growth_ratio", "value": "1.469869"},
                            {"index_id": "calculate_parent_holder_net_profit_yoy_growth_ratio", "value": "-1.951595"},
                        ]
                    }
                ]
            }
        return financial_handler(path, params)

    p, _ = provider(handler)
    growth = FuyaoFundamentalAdapter(p).get_fundamental_bundle(SYMBOL)["growth"]
    assert growth["revenue_yoy"] == 1.469869 and growth["net_profit_yoy"] == -1.951595
    assert "abilities" not in growth


def test_dragon_tiger_lookback_deduplicates_days_and_preserves_partial_results(monkeypatch):
    today = datetime.now().date()
    latest, previous = today - timedelta(days=1), today - timedelta(days=2)
    monkeypatch.setattr(
        "finance_analysis.integrations.market_data.fundamental_adapter.get_trading_days_between",
        lambda *args: [previous, latest],
    )

    def handler(path, params):
        if params.get("date") == previous.isoformat():
            return httpx.Response(200, json={"code": 5002})
        return {"trade_date": latest.isoformat(), "stock_items": [{"thscode": SYMBOL}, {"thscode": SYMBOL}]}

    p, _ = provider(handler)
    result = FuyaoFundamentalAdapter(p).get_dragon_tiger_flag(SYMBOL)
    assert result["is_on_list"] and result["recent_count"] == 1
    assert result["status"] == "partial" and result["errors"]

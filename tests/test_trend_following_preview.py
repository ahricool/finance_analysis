from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from fastapi import HTTPException

from finance_analysis.integrations.market_data.models import Adjustment, Market, MarketBar, MarketQuote  # pragma: allowlist secret
from finance_analysis.integrations.market_data.preview import (  # pragma: allowlist secret
    PreviewQuoteError,
    collect_preview_daily_bars,
    daily_bar_from_quote,
)
from finance_analysis.integrations.market_data.providers.easyquotation import (  # pragma: allowlist secret
    EasyQuotationProvider,
    canonical_to_tencent_code,
    tencent_code_to_canonical,
)
from finance_analysis.integrations.market_data.providers.yfinance import YFinanceProvider  # pragma: allowlist secret
from finance_analysis.tasks.lifecycle import TaskSkipped  # pragma: allowlist secret
from finance_analysis.trend_following.config import DEFAULT_CONFIG  # pragma: allowlist secret
from finance_analysis.trend_following.models import DailyBar, UniverseMember  # pragma: allowlist secret
from finance_analysis.trend_following.preview_cache import PREVIEW_KEY_TEMPLATE, json_ready, load_preview, save_preview  # pragma: allowlist secret
from finance_analysis.trend_following.service import TrendFollowingService  # pragma: allowlist secret

TRADE_DATE = date(2026, 8, 24)


def _overlay_bar(close: float) -> DailyBar:
    return DailyBar(TRADE_DATE, close - 0.5, close + 1, close - 1, close, 10_000.0, None)


class PreviewRepository:
    market = "US"

    def __init__(self):
        self.previous_calls = []
        self.replace_calls = []
        self.upserted_dates = []
        self.states = {}

    def daily_codes_on_date(self, codes, trade_date):
        return set(codes)

    def load_daily_history(self, codes, trade_date, *, calendar_lookback_days):
        result = []
        specs = (("AAA.US", 1.2), ("BBB.US", 0.5), ("SPY.US", 0.7))
        selected = set(codes)
        for code, step in specs:
            if code not in selected:
                continue
            for index in range(80):
                close = 100 + index * step
                history_date = trade_date - timedelta(days=79 - index)
                if history_date > trade_date:
                    continue
                result.append(
                    {
                        "instrument_id": 1,
                        "code": code,
                        "name": code,
                        "trade_date": history_date,
                        "open": close - 0.5,
                        "high": close + 1,
                        "low": close - 1,
                        "close": close,
                        "volume": 1_000 + index * 100,
                        "amount": None,
                    }
                )
        return result

    def previous_snapshots(self, trade_date, codes):
        self.previous_calls.append((trade_date, set(codes)))
        return {code: payload for code, payload in self.states.items() if payload["trade_date"] < trade_date}

    def latest_snapshot_date(self):
        return None

    def replace_day(self, trade_date, snapshots, summary):
        self.replace_calls.append(trade_date)
        self.upserted_dates.append(trade_date)
        for item in snapshots:
            self.states[item["code"]] = item
        return len(snapshots)

    def invalidate_from(self, trade_date):
        raise AssertionError(f"preview must not invalidate official state: {trade_date}")


def _history_rows(code, trade_date, step):
    rows = []
    for index in range(80):
        close = 100 + index * step
        rows.append(
            {
                "instrument_id": 1,
                "code": code,
                "name": code,
                "trade_date": trade_date - timedelta(days=79 - index),
                "open": close - 0.5,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume": 1_000 + index * 100,
                "amount": None,
            }
        )
    return rows


def _forward_market_data(bars_by_code):
    calls = []

    class MarketData:
        def get_daily_bars(self, codes, start, end, **options):
            calls.append((list(codes), start, end, options))
            assert options == {"adjustment": "forward", "source_policy": "db_fresh"}
            return SimpleNamespace(
                data={code: [SimpleNamespace(**row) for row in bars_by_code[code]] for code in codes}
            )

    return MarketData(), calls


def test_tencent_prefixed_codes_keep_exchange_and_do_not_collide_indexes():
    assert tencent_code_to_canonical("sz000001") == "000001.SZ"
    assert tencent_code_to_canonical("sh000001") == "000001.SH"
    assert tencent_code_to_canonical("sh600519") == "600519.SH"
    assert tencent_code_to_canonical("sh510300") == "510300.SH"
    assert canonical_to_tencent_code("000001.SZ") == "sz000001"
    assert canonical_to_tencent_code("510300.SH") == "sh510300"


def test_easyquotation_snapshot_maps_tencent_fields():
    payload = {
        "sz000001": {
            "name": "平安银行",
            "now": 11.2,
            "close": 11.0,
            "open": 11.05,
            "high": 11.3,
            "low": 10.9,
            "volume": 22545000,
            "成交额(万)": 202704887.74,
            "datetime": datetime(2026, 9, 10, 14, 30, 0),
        },
        "sh600519": {
            "name": "贵州茅台",
            "now": 1800.0,
            "close": 1780.0,
            "open": 1785.0,
            "high": 1810.0,
            "low": 1770.0,
            "volume": 12300,
            "成交额(万)": 2.2e9,
            "datetime": datetime(2026, 9, 10, 14, 30, 0),
        },
    }
    provider = EasyQuotationProvider(client_factory=lambda: SimpleNamespace(market_snapshot=lambda prefix: payload))
    result = provider.fetch_market_snapshot(Market.CN)
    assert set(result.data) == {"000001.SZ", "600519.SH"}
    maotai = result.data["600519.SH"]
    assert maotai.price == 1800.0
    assert maotai.open_price == 1785.0
    assert maotai.high == 1810.0
    assert maotai.low == 1770.0
    assert maotai.pre_close == 1780.0
    assert maotai.volume == 12300
    assert maotai.amount == 2.2e9
    bar = daily_bar_from_quote(maotai, date(2026, 9, 10))
    assert bar is not None
    assert (bar.open, bar.high, bar.low, bar.close, bar.volume) == (1785.0, 1810.0, 1770.0, 1800.0, 12300)



def _quote_row(name, now, close, open_, high, low, volume, amount):
    return {
        "name": name,
        "now": now,
        "close": close,
        "open": open_,
        "high": high,
        "low": low,
        "volume": volume,
        "成交额(万)": amount,
        "datetime": datetime(2026, 9, 10, 14, 30, 0),
    }



def test_easyquotation_keeps_sz_and_sh_000001_separate():
    payload = {
        "sz000001": _quote_row("平安银行", 11.2, 11.0, 11.05, 11.3, 10.9, 22545000, 2.0e8),
        "sh000001": _quote_row("上证指数", 3200.0, 3180.0, 3190.0, 3210.0, 3170.0, 1, 1.0),
        "sh600519": _quote_row("贵州茅台", 1800.0, 1780.0, 1785.0, 1810.0, 1770.0, 12300, 2.2e9),
    }
    provider = EasyQuotationProvider(client_factory=lambda: SimpleNamespace(market_snapshot=lambda prefix: payload))
    result = provider.fetch_market_snapshot(Market.CN)
    assert result.data["000001.SZ"].name == "平安银行"
    assert result.data["000001.SZ"].price == 11.2
    assert result.data["000001.SH"].name == "上证指数"
    assert result.data["000001.SH"].price == 3200.0
    assert result.data["600519.SH"].name == "贵州茅台"


def test_cn_preview_fills_missing_etf_via_same_provider_real_batch():
    snapshot_payload = {
        "sz000001": _quote_row("平安银行", 11.2, 11.0, 11.05, 11.3, 10.9, 22545000, 2.0e8),
        "sh000001": _quote_row("上证指数", 3200.0, 3180.0, 3190.0, 3210.0, 3170.0, 1, 1.0),
        "sh600519": _quote_row("贵州茅台", 1800.0, 1780.0, 1785.0, 1810.0, 1770.0, 12300, 2.2e9),
    }
    real_payload = {
        "sh510300": _quote_row("沪深300ETF", 4.12, 4.10, 4.11, 4.15, 4.08, 1_000_000, 4.1e8),
    }
    real_calls = []

    class Client:
        def market_snapshot(self, prefix=True):
            return snapshot_payload

        def real(self, stock_codes, prefix=True):
            real_calls.append((list(stock_codes), prefix))
            return real_payload

    provider = EasyQuotationProvider(client_factory=lambda: Client())
    market_data = SimpleNamespace(
        get_market_snapshot=lambda market, providers=None: provider.fetch_market_snapshot(market),
        registry=SimpleNamespace(get=lambda name: SimpleNamespace(provider=provider)),
    )
    bars, label, quote_count = collect_preview_daily_bars(
        market_data,
        "CN",
        ["000001.SZ", "600519.SH", "510300.SH"],
        date(2026, 9, 10),
    )
    assert label == "easyquotation_tencent"
    assert quote_count == 3
    assert bars["000001.SZ"].close == 11.2
    assert bars["600519.SH"].close == 1800.0
    assert bars["510300.SH"].close == 4.12
    assert bars["510300.SH"].open == 4.11
    assert bars["510300.SH"].high == 4.15
    assert bars["510300.SH"].low == 4.08
    assert bars["510300.SH"].volume == 1_000_000
    assert "000001.SH" not in bars
    assert real_calls == [(["sh510300"], True)]


def test_cn_preview_does_not_call_real_when_snapshot_covers_universe():
    snapshot_payload = {
        "sz000001": _quote_row("平安银行", 11.2, 11.0, 11.05, 11.3, 10.9, 22545000, 2.0e8),
        "sh510300": _quote_row("沪深300ETF", 4.12, 4.10, 4.11, 4.15, 4.08, 1_000_000, 4.1e8),
    }
    real_calls = []

    class Client:
        def market_snapshot(self, prefix=True):
            return snapshot_payload

        def real(self, stock_codes, prefix=True):
            real_calls.append(stock_codes)
            return {}

    provider = EasyQuotationProvider(client_factory=lambda: Client())
    market_data = SimpleNamespace(
        get_market_snapshot=lambda market, providers=None: provider.fetch_market_snapshot(market),
        registry=SimpleNamespace(get=lambda name: SimpleNamespace(provider=provider)),
    )
    bars, _, _ = collect_preview_daily_bars(
        market_data,
        "CN",
        ["000001.SZ", "510300.SH"],
        date(2026, 9, 10),
    )
    assert set(bars) == {"000001.SZ", "510300.SH"}
    assert real_calls == []


def test_easyquotation_empty_snapshot_fails_without_fallback():
    provider = EasyQuotationProvider(client_factory=lambda: SimpleNamespace(market_snapshot=lambda prefix: {}))
    with pytest.raises(RuntimeError, match="empty snapshot"):
        provider.fetch_market_snapshot(Market.CN)


def test_yfinance_preview_aggregates_5m_batch(monkeypatch):
    captured = {}

    def download(**kwargs):
        captured.update(kwargs)
        index = pd.DatetimeIndex(
            ["2026-09-10 09:30:00-04:00", "2026-09-10 09:35:00-04:00", "2026-09-10 09:40:00-04:00"],
            name="Datetime",
        )
        frames = {}
        samples = (("AAPL", [100.0, 101.0, 102.0]), ("NVDA", [200.0, 198.0, 199.0]), ("MSFT", [50.0, 51.0, 49.5]))
        for ticker, closes in samples:
            frames[ticker] = pd.DataFrame(
                {
                    "Open": [closes[0], closes[1], closes[1]],
                    "High": [closes[0] + 1, closes[1] + 2, closes[2] + 1],
                    "Low": [closes[0] - 1, closes[1] - 2, closes[2] - 1],
                    "Close": closes,
                    "Volume": [10, 20, 30],
                },
                index=index,
            )
        return pd.concat(frames, axis=1)

    monkeypatch.setattr("yfinance.download", download)
    result = YFinanceProvider(batch_size=10, max_workers=1, max_retries=0).fetch_intraday_preview_daily_bars(
        ["AAPL.US", "NVDA.US", "MSFT.US"],
        date(2026, 9, 10),
    )
    assert captured["interval"] == "5m"
    assert captured["period"] == "1d"
    assert captured["auto_adjust"] is False
    apple = result.data["AAPL.US"][0]
    assert apple.open == 100.0
    assert apple.close == 102.0
    assert apple.high == 103.0
    assert apple.low == 99.0
    assert apple.volume == 60
    assert apple.amount is None
    assert apple.adjustment is Adjustment.RAW


def test_preview_reuses_previous_official_snapshot_and_does_not_persist(monkeypatch):
    repository = PreviewRepository()
    monkeypatch.setattr(
        "finance_analysis.trend_following.service.get_universe",  # pragma: allowlist secret
        lambda market: (UniverseMember("US", "AAA.US", "AAA"), UniverseMember("US", "BBB.US", "BBB")),
    )
    overlay = {
        "AAA.US": _overlay_bar(200.0),
        "BBB.US": _overlay_bar(140.0),
        "SPY.US": _overlay_bar(160.0),
    }
    bars = {
        code: MarketBar(
            symbol=code,
            market=Market.US,
            interval="1d",
            trade_date=TRADE_DATE,
            bar_time=None,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=int(bar.volume),
            amount=bar.amount,
            currency="USD",
            adjustment=Adjustment.RAW,
            provider="yfinance",
        )
        for code, bar in overlay.items()
    }
    monkeypatch.setattr(
        "finance_analysis.trend_following.service.collect_preview_daily_bars",  # pragma: allowlist secret
        lambda *args, **kwargs: (bars, "yfinance", 3),
    )
    monkeypatch.setattr("finance_analysis.trend_following.service.save_preview", lambda *args, **kwargs: None)  # pragma: allowlist secret
    spy_rows = repository.load_daily_history({"SPY.US"}, TRADE_DATE, calendar_lookback_days=500)
    market_data, _ = _forward_market_data({"SPY.US": spy_rows})
    service = TrendFollowingService("US", repository, market_data=market_data)
    first = service.run_preview(TRADE_DATE)
    second = service.run_preview(TRADE_DATE)
    assert first["status"] == "completed"
    assert second["status"] == "completed"
    assert repository.replace_calls == []
    assert [item[0] for item in repository.previous_calls] == [TRADE_DATE, TRADE_DATE]
    assert first["provider"] == "yfinance"
    assert "snapshots" in first


def test_official_run_after_preview_still_inherits_previous_official_state(monkeypatch):
    repository = PreviewRepository()
    monkeypatch.setattr(
        "finance_analysis.trend_following.service.get_universe",  # pragma: allowlist secret
        lambda market: (UniverseMember("US", "AAA.US", "AAA"), UniverseMember("US", "BBB.US", "BBB")),
    )
    overlay = {
        "AAA.US": _overlay_bar(200.0),
        "BBB.US": _overlay_bar(140.0),
        "SPY.US": _overlay_bar(160.0),
    }
    monkeypatch.setattr(
        "finance_analysis.trend_following.service.collect_preview_daily_bars",  # pragma: allowlist secret
        lambda *args, **kwargs: (overlay, "yfinance", 3),
    )
    monkeypatch.setattr("finance_analysis.trend_following.service.save_preview", lambda *args, **kwargs: None)  # pragma: allowlist secret

    class MarketData:
        def get_daily_bars(self, codes, start, end, **options):
            rows = repository.load_daily_history({"AAA.US", "BBB.US", "SPY.US"}, end, calendar_lookback_days=500)
            spy = [SimpleNamespace(**row) for row in rows if row["code"] == "SPY.US"]
            spy.append(SimpleNamespace(trade_date=end, open=160, high=161, low=159, close=160, volume=1000, amount=None))
            return SimpleNamespace(data={"SPY.US": spy})

    service = TrendFollowingService("US", repository, market_data=MarketData())
    service.run_preview(TRADE_DATE)
    official = service.run(TRADE_DATE)
    assert official["status"] == "completed"
    assert repository.replace_calls == [TRADE_DATE]
    assert repository.previous_calls[0][0] == TRADE_DATE
    assert repository.previous_calls[-1][0] == TRADE_DATE




def test_cn_preview_completes_with_csi2000_db_fresh_history(monkeypatch):
    codes = ("600001.SH", "600002.SH", "600003.SH")
    csi2000 = {"600002.SH", "600003.SH"}
    monkeypatch.setattr(
        "finance_analysis.trend_following.service.get_universe",  # pragma: allowlist secret
        lambda market: tuple(UniverseMember("CN", code, code) for code in codes),
    )
    monkeypatch.setattr(
        "finance_analysis.trend_following.service.UniverseResolver",  # pragma: allowlist secret
        lambda: SimpleNamespace(resolve_universe=lambda key: [SimpleNamespace(code=code) for code in sorted(csi2000)]),
    )
    overlay = {code: _overlay_bar(200.0 + index) for index, code in enumerate(codes)}
    overlay["510300.SH"] = _overlay_bar(160.0)
    monkeypatch.setattr(
        "finance_analysis.trend_following.service.collect_preview_daily_bars",  # pragma: allowlist secret
        lambda *args, **kwargs: (overlay, "easyquotation_tencent", 4),
    )
    saved = []
    monkeypatch.setattr(
        "finance_analysis.trend_following.service.save_preview",  # pragma: allowlist secret
        lambda market, payload: saved.append(payload),
    )

    class Repository(PreviewRepository):
        market = "CN"

        def load_daily_history(self, requested, trade_date, *, calendar_lookback_days):
            assert set(requested) == {"600001.SH"}
            return _history_rows("600001.SH", trade_date, 1.2)

    repository = Repository()
    bars_by_code = {
        "600002.SH": _history_rows("600002.SH", TRADE_DATE, 0.8),
        "600003.SH": _history_rows("600003.SH", TRADE_DATE, 0.6),
        "510300.SH": _history_rows("510300.SH", TRADE_DATE, 0.7),
    }
    market_data, calls = _forward_market_data(bars_by_code)
    service = TrendFollowingService("CN", repository, market_data=market_data)
    result = service.run_preview(TRADE_DATE)
    assert DEFAULT_CONFIG.minimum_data_coverage == 0.95
    assert result["status"] == "completed"
    assert result["data_coverage"] == 1.0
    assert result["rankable_count"] == 3
    snapshot_codes = {item["code"] for item in result["snapshots"]}
    assert snapshot_codes >= set(codes)
    assert {item["code"] for item in saved[0]["snapshots"]} >= csi2000
    assert repository.replace_calls == []
    assert repository.previous_calls == [(TRADE_DATE, set(codes))]
    assert calls[0][0] == ["600002.SH", "600003.SH"]
    assert calls[1][0] == ["510300.SH"]
    assert all(call[3] == {"adjustment": "forward", "source_policy": "db_fresh"} for call in calls)
    csi_row = next(item for item in result["snapshots"] if item["code"] == "600002.SH")
    assert csi_row["reference_price"] == overlay["600002.SH"].close


def test_preview_task_result_omits_snapshots(monkeypatch):
    from finance_analysis.tasks.celery.jobs.trend_following import tasks  # pragma: allowlist secret

    monkeypatch.setattr(tasks, "is_market_open", lambda market, day: True)

    class Service:
        def __init__(self, market):
            self.market = market

        def run_preview(self, requested):
            return {
                "status": "completed",
                "market": "CN",
                "trade_date": requested.isoformat(),
                "preview_time": "2026-09-10T03:00:00+00:00",
                "provider": "easyquotation_tencent",
                "quote_count": 10,
                "universe_size": 3,
                "data_coverage": 1.0,
                "rankable_count": 3,
                "snapshot_count": 3,
                "candidate_count": 1,
                "elapsed_seconds": 1.2,
                "warnings": [],
                "snapshots": [{"code": "600001.SH"}, {"code": "600002.SH"}],
                "features": {"ignored": True},
            }

    monkeypatch.setattr(tasks, "TrendFollowingService", Service)
    result = tasks._run_preview("CN", "2026-09-10")
    assert "snapshots" not in result
    assert "features" not in result
    assert result["status"] == "completed"
    assert result["snapshot_count"] == 3
    assert result["provider"] == "easyquotation_tencent"


def test_cn_snapshot_failure_raises_and_does_not_write_snapshots(monkeypatch):
    repository = PreviewRepository()
    repository.market = "CN"
    monkeypatch.setattr(
        "finance_analysis.trend_following.service.get_universe",  # pragma: allowlist secret
        lambda market: (UniverseMember("CN", "600519.SH", "茅台"),),
    )
    monkeypatch.setattr(
        "finance_analysis.trend_following.service.collect_preview_daily_bars",  # pragma: allowlist secret
        lambda *args, **kwargs: (_ for _ in ()).throw(PreviewQuoteError("easyquotation tencent snapshot failed")),
    )
    saved = []
    monkeypatch.setattr("finance_analysis.trend_following.service.save_preview", lambda market, payload: saved.append(payload))  # pragma: allowlist secret
    service = TrendFollowingService("CN", repository, market_data=SimpleNamespace())
    with pytest.raises(PreviewQuoteError, match="easyquotation tencent snapshot failed"):
        service.run_preview(TRADE_DATE)
    assert repository.replace_calls == []
    assert saved[0]["status"] == "failed"


def test_preview_task_skips_non_trading_days(monkeypatch):
    from finance_analysis.tasks.celery.jobs.trend_following import tasks  # pragma: allowlist secret

    monkeypatch.setattr(tasks, "is_market_open", lambda market, day: False)
    monkeypatch.setattr(
        tasks,
        "get_market_now",
        lambda market: datetime(2026, 10, 1, 11, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    with pytest.raises(TaskSkipped, match="不是交易日"):
        tasks._run_preview("CN", None)


def test_preview_cache_round_trip():
    stored = {}

    class Redis:
        def set(self, key, value, ex=None):
            stored["key"] = key
            stored["value"] = value
            stored["ex"] = ex

        def get(self, key):
            return stored["value"] if stored.get("key") == key else None

    payload = {
        "market": "CN",
        "trade_date": TRADE_DATE,
        "preview_time": datetime(2026, 8, 24, 3, 0, tzinfo=ZoneInfo("UTC")),
        "status": "completed",
        "snapshots": [{"code": "600519.SH", "trade_date": TRADE_DATE}],
    }
    client = Redis()
    save_preview("CN", payload, client=client)
    assert stored["key"] == PREVIEW_KEY_TEMPLATE.format(market="CN")
    assert stored["ex"] == 24 * 60 * 60
    loaded = load_preview("CN", client=client)
    assert loaded["market"] == "CN"
    assert loaded["trade_date"] == "2026-08-24"
    assert loaded["snapshots"][0]["code"] == "600519.SH"


def test_preview_api_returns_cached_payload(monkeypatch):
    from finance_analysis.interfaces.api.v1.endpoints import trend_following  # pragma: allowlist secret

    monkeypatch.setattr(
        trend_following,
        "load_preview",
        lambda market: {"market": market, "status": "completed", "snapshots": [], "trade_date": "2026-09-10"},
    )
    payload = asyncio.run(trend_following.preview(SimpleNamespace(id=1), "CN"))
    assert payload["status"] == "completed"
    assert payload["market"] == "CN"


def test_preview_api_404_when_missing(monkeypatch):
    from finance_analysis.interfaces.api.v1.endpoints import trend_following  # pragma: allowlist secret

    monkeypatch.setattr(trend_following, "load_preview", lambda market: None)
    with pytest.raises(HTTPException) as error:
        asyncio.run(trend_following.preview(SimpleNamespace(id=1), "US"))
    assert error.value.status_code == 404


def test_json_ready_serializes_dates():
    encoded = json.dumps(json_ready({"trade_date": TRADE_DATE, "nested": [DEFAULT_CONFIG.history_bars]}))
    assert "2026-08-24" in encoded


def test_daily_bar_from_quote_rejects_invalid_ohlc():
    quote = MarketQuote(
        symbol="600519.SH",
        market=Market.CN,
        provider="easyquotation",
        currency="CNY",
        price=10.0,
        open_price=11.0,
        high=10.5,
        low=9.0,
        volume=1,
    )
    assert daily_bar_from_quote(quote, TRADE_DATE) is None

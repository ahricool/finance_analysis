from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from fastapi import HTTPException

from finance_analysis.etf_rotation.models import DailyBar  # pragma: allowlist secret
from finance_analysis.etf_rotation.preview_cache import (  # pragma: allowlist secret
    PREVIEW_KEY_TEMPLATE,
    load_preview,
    save_preview,
)
from finance_analysis.etf_rotation.service import ETFRotationService  # pragma: allowlist secret
from finance_analysis.etf_rotation.universe import ETFUniverseMember  # pragma: allowlist secret
from finance_analysis.integrations.market_data.models import (  # pragma: allowlist secret
    Adjustment,
    Market,
    MarketBar,
)
from finance_analysis.integrations.market_data.preview import (  # pragma: allowlist secret
    PreviewQuoteError,
    close_bar_from_quote,
    collect_preview_daily_bars,
    collect_symbol_preview_daily_bars,
)
from finance_analysis.integrations.market_data.providers.easyquotation import (  # pragma: allowlist secret
    EasyQuotationProvider,
)
from finance_analysis.integrations.market_data.providers.yfinance import (  # pragma: allowlist secret
    YFinanceProvider,
)
from finance_analysis.tasks.lifecycle import TaskSkipped  # pragma: allowlist secret

TRADE_DATE = date(2026, 8, 25)
CN_MEMBERS = (
    ETFUniverseMember("588000.SH", "科创50ETF", "BROAD_INDEX", "STAR50", "GROWTH", market="CN"),
    ETFUniverseMember("159915.SZ", "创业板ETF", "BROAD_INDEX", "CHINEXT", "GROWTH", market="CN"),
)
US_MEMBERS = (
    ETFUniverseMember("SPY.US", "S&P 500 ETF", "TEST", "TEST", "TEST", market="US"),
    ETFUniverseMember("QQQ.US", "Nasdaq 100 ETF", "TEST", "TEST", "TEST", market="US"),
)


def _quote_row(name, now, close, open_, high, low, volume, amount, quoted_at=None):
    return {
        "name": name,
        "now": now,
        "close": close,
        "open": open_,
        "high": high,
        "low": low,
        "volume": volume,
        "成交额(万)": amount,
        "datetime": quoted_at if quoted_at is not None else datetime(2026, 9, 10, 11, 5, 0),
    }


class PreviewRepository:
    def __init__(self, market="CN", previous_candidates=None):
        self.market = market
        self.previous_candidates = set(previous_candidates or ())
        self.previous_calls = []
        self.rank_calls = []
        self.market_write_calls = 0
        self.snapshot_write_calls = 0
        self.saved = {}
        self.market_snapshot = None

    def historical_composite_ranks(self, trade_date, codes):
        self.rank_calls.append((trade_date, set(codes)))
        return {}

    def previous_candidate_codes(self, trade_date):
        self.previous_calls.append(trade_date)
        return set(self.previous_candidates)

    def upsert_market_snapshot(self, snapshot):
        self.market_write_calls += 1
        self.market_snapshot = dict(snapshot)

    def upsert_snapshots(self, snapshots):
        self.snapshot_write_calls += 1
        for snapshot in snapshots:
            self.saved[(snapshot["trade_date"].isoformat(), snapshot["code"])] = dict(snapshot)
        return len(snapshots)


def _history_market_data(*, stale_today_close=50.0):
    class MarketData:
        def get_daily_bars(self, requested, start, end, **options):
            assert options == {"adjustment": "forward", "source_policy": "db_fresh"}
            data = {}
            for code in requested:
                bars = []
                for index in range(40):
                    day = TRADE_DATE - timedelta(days=39 - index)
                    close = 100 + index if day < TRADE_DATE else stale_today_close
                    bars.append(
                        SimpleNamespace(
                            trade_date=day,
                            close=close,
                            volume=1_000 + index,
                            amount=100_000_000 + index,
                        )
                    )
                data[code] = bars
            return SimpleNamespace(data=data)

    return MarketData()


def _overlay_bars(closes: dict[str, float], *, volume=20_000, amount=4.1e8, provider="easyquotation"):
    return {
        code: MarketBar(
            symbol=code,
            market=Market.CN if code.endswith((".SH", ".SZ")) else Market.US,
            interval="1d",
            trade_date=TRADE_DATE,
            bar_time=None,
            open=close,
            high=close,
            low=close,
            close=close,
            volume=volume,
            amount=amount,
            currency="CNY" if code.endswith((".SH", ".SZ")) else "USD",
            adjustment=Adjustment.RAW,
            provider=provider,
        )
        for code, close in closes.items()
    }


def test_cn_etf_preview_uses_tencent_real_not_market_snapshot():
    snapshot_calls = []
    real_calls = []
    payload = {
        "sh588000": _quote_row("科创50ETF", 1.23, 1.20, 1.21, 1.25, 1.19, 8000, 9.8e7),
        "sz159915": _quote_row("创业板ETF", 2.34, 2.30, 2.31, 2.36, 2.28, 9000, 1.1e8),
        "sh510300": _quote_row("沪深300ETF", 4.12, 4.10, 4.11, 4.15, 4.08, 1_000_000, 4.1e8),
    }

    class Client:
        def market_snapshot(self, prefix=True):
            snapshot_calls.append(prefix)
            raise AssertionError("ETF Rotation preview must not use market_snapshot")

        def real(self, stock_codes, prefix=True):
            real_calls.append((list(stock_codes), prefix))
            return payload

    provider = EasyQuotationProvider(client_factory=lambda: Client())
    market_data = SimpleNamespace(
        get_market_snapshot=lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("snapshot")),
        registry=SimpleNamespace(get=lambda name: SimpleNamespace(provider=provider)),
    )
    bars, label, quote_count, data_as_of = collect_symbol_preview_daily_bars(
        market_data,
        "CN",
        ["588000.SH", "159915.SZ", "510300.SH"],
        date(2026, 9, 10),
    )
    assert snapshot_calls == []
    assert label == "easyquotation_tencent"
    assert quote_count == 3
    assert real_calls == [(["sh588000", "sz159915", "sh510300"], True)]
    assert bars["588000.SH"].close == 1.23
    assert bars["588000.SH"].volume == 8000
    assert bars["588000.SH"].amount == 9.8e7
    assert bars["510300.SH"].close == 4.12
    assert data_as_of == datetime(2026, 9, 10, 3, 5, tzinfo=timezone.utc)
    converted = DailyBar(
        trade_date=bars["510300.SH"].trade_date,
        close=bars["510300.SH"].close,
        volume=float(bars["510300.SH"].volume),
        amount=bars["510300.SH"].amount,
    )
    assert converted == DailyBar(date(2026, 9, 10), 4.12, 1_000_000.0, 4.1e8)


def test_close_bar_from_quote_does_not_require_ohlc():
    from finance_analysis.integrations.market_data.providers.easyquotation import (  # pragma: allowlist secret
        quote_from_tencent_row,
    )

    quote = quote_from_tencent_row(
        "sh510300",
        {"name": "沪深300ETF", "now": 4.12, "volume": 1234, "成交额(万)": 5.5e7},
    )
    bar = close_bar_from_quote(quote, date(2026, 9, 10))
    assert bar is not None
    assert bar.close == 4.12
    assert bar.volume == 1234
    assert bar.amount == 5.5e7
    assert bar.open == bar.high == bar.low == 4.12


def test_cn_symbol_preview_missing_one_etf_does_not_fail_the_batch():
    class Client:
        def real(self, stock_codes, prefix=True):
            return {
                "sh588000": _quote_row("科创50ETF", 1.23, 1.20, 1.21, 1.25, 1.19, 8000, 9.8e7),
                "sh510300": _quote_row("沪深300ETF", 4.12, 4.10, 4.11, 4.15, 4.08, 1_000_000, 4.1e8),
            }

        def market_snapshot(self, prefix=True):
            raise AssertionError("must not snapshot")

    provider = EasyQuotationProvider(client_factory=lambda: Client())
    market_data = SimpleNamespace(registry=SimpleNamespace(get=lambda name: SimpleNamespace(provider=provider)))
    bars, _, quote_count, data_as_of = collect_symbol_preview_daily_bars(
        market_data,
        "CN",
        ["588000.SH", "159915.SZ", "510300.SH"],
        date(2026, 9, 10),
    )
    assert quote_count == 2
    assert "159915.SZ" not in bars
    assert set(bars) == {"588000.SH", "510300.SH"}
    assert data_as_of == datetime(2026, 9, 10, 3, 5, tzinfo=timezone.utc)


def test_cn_symbol_preview_empty_real_raises():
    class Client:
        def real(self, stock_codes, prefix=True):
            return {}

    provider = EasyQuotationProvider(client_factory=lambda: Client())
    market_data = SimpleNamespace(registry=SimpleNamespace(get=lambda name: SimpleNamespace(provider=provider)))
    with pytest.raises(PreviewQuoteError, match="real failed"):
        collect_symbol_preview_daily_bars(market_data, "CN", ["588000.SH"], date(2026, 9, 10))


def test_trend_following_cn_preview_still_uses_market_snapshot():
    snapshot_payload = {
        "sh588000": _quote_row("科创50ETF", 1.23, 1.20, 1.21, 1.25, 1.19, 8000, 9.8e7),
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
    bars, label, quote_count, data_as_of = collect_preview_daily_bars(
        market_data, "CN", ["588000.SH", "510300.SH"], date(2026, 9, 10)
    )
    assert label == "easyquotation_tencent"
    assert quote_count == 2
    assert set(bars) == {"588000.SH", "510300.SH"}
    assert real_calls == []
    assert data_as_of == datetime(2026, 9, 10, 3, 5, tzinfo=timezone.utc)


def test_us_etf_preview_uses_yfinance_5m_batch_not_fast_info(monkeypatch):
    captured = {}
    ticker_calls = []

    class Ticker:
        def __init__(self, symbol):
            ticker_calls.append(symbol)

        @property
        def fast_info(self):
            raise AssertionError("ETF Rotation preview must not use Ticker.fast_info")

    def download(*args, **kwargs):
        symbols = args[0] if args else kwargs.get("tickers")
        captured["symbols"] = list(symbols)
        captured.update(kwargs)
        index = pd.DatetimeIndex(
            ["2026-09-10 09:30:00-04:00", "2026-09-10 09:35:00-04:00"],
            name="Datetime",
        )
        frames = {}
        for ticker in captured["symbols"]:
            frames[ticker] = pd.DataFrame(
                {
                    "Open": [100.0, 101.0],
                    "High": [102.0, 103.0],
                    "Low": [99.0, 100.0],
                    "Close": [101.0, 104.0],
                    "Volume": [10, 20],
                },
                index=index,
            )
        return pd.concat(frames, axis=1)

    monkeypatch.setattr("yfinance.download", download)
    monkeypatch.setattr("yfinance.Ticker", Ticker)
    codes = [member.code for member in US_MEMBERS]
    provider = YFinanceProvider(batch_size=50, max_workers=1, max_retries=0)
    market_data = SimpleNamespace(registry=SimpleNamespace(get=lambda name: SimpleNamespace(provider=provider)))
    bars, label, quote_count, data_as_of = collect_symbol_preview_daily_bars(market_data, "US", codes, date(2026, 9, 10))
    assert label == "yfinance"
    assert ticker_calls == []
    assert captured["interval"] == "5m"
    assert captured["period"] == "1d"
    assert set(captured["symbols"]) == {"SPY", "QQQ"}
    assert quote_count == 2
    assert bars["SPY.US"].close == 104.0
    assert bars["SPY.US"].volume == 30
    assert bars["SPY.US"].amount is None
    assert data_as_of == datetime(2026, 9, 10, 13, 35, tzinfo=timezone.utc)


def test_cn_etf_data_as_of_uses_max_converted_quote_time():
    class Client:
        def real(self, stock_codes, prefix=True):
            return {
                "sh588000": _quote_row(
                    "科创50ETF", 1.23, 1.20, 1.21, 1.25, 1.19, 8000, 9.8e7,
                    quoted_at=datetime(2026, 9, 10, 11, 5, 12),
                ),
                "sz159915": _quote_row(
                    "创业板ETF", 2.34, 2.30, 2.31, 2.36, 2.28, 9000, 1.1e8,
                    quoted_at=datetime(2026, 9, 10, 14, 34, 57),
                ),
                "sh510300": {
                    "name": "沪深300ETF",
                    "now": 4.12,
                    "close": 4.10,
                    "open": 4.11,
                    "high": 4.15,
                    "low": 4.08,
                    "volume": 1_000_000,
                    "成交额(万)": 4.1e8,
                },
            }

        def market_snapshot(self, prefix=True):
            raise AssertionError("must not snapshot")

    provider = EasyQuotationProvider(client_factory=lambda: Client())
    market_data = SimpleNamespace(registry=SimpleNamespace(get=lambda name: SimpleNamespace(provider=provider)))
    _, _, _, data_as_of = collect_symbol_preview_daily_bars(
        market_data,
        "CN",
        ["588000.SH", "159915.SZ", "510300.SH"],
        date(2026, 9, 10),
    )
    assert data_as_of == datetime(2026, 9, 10, 6, 34, 57, tzinfo=timezone.utc)


def test_preview_replaces_stale_today_bar_with_realtime_close(monkeypatch):
    repository = PreviewRepository(previous_candidates={"588000.SH"})
    monkeypatch.setattr(
        "finance_analysis.etf_rotation.service.enabled_etfs",  # pragma: allowlist secret
        lambda market: CN_MEMBERS,
    )
    overlay = _overlay_bars({"588000.SH": 1.88, "159915.SZ": 2.66, "510300.SH": 4.55})
    monkeypatch.setattr(
        "finance_analysis.etf_rotation.service.collect_symbol_preview_daily_bars",  # pragma: allowlist secret
        lambda *args, **kwargs: (overlay, "easyquotation_tencent", 3, datetime(2026, 9, 10, 6, 34, 57, tzinfo=timezone.utc)),
    )
    saved = []
    monkeypatch.setattr(
        "finance_analysis.etf_rotation.service.save_preview",  # pragma: allowlist secret
        lambda market, payload: saved.append(payload),
    )
    service = ETFRotationService("CN", repository, market_data=_history_market_data())
    result = service.run_preview(TRADE_DATE)
    by_code = {item["code"]: item for item in result["items"]}
    assert result["status"] == "completed"
    assert result["data_as_of"] == "2026-09-10T06:34:57.000Z"
    assert by_code["588000.SH"]["reference_price"] == pytest.approx(1.88)
    assert by_code["159915.SZ"]["reference_price"] == pytest.approx(2.66)
    assert repository.market_write_calls == repository.snapshot_write_calls == 0
    assert repository.previous_calls == [TRADE_DATE]
    assert repository.rank_calls[0][0] == TRADE_DATE
    assert saved[0]["items"]
    assert saved[0]["provider"] == "easyquotation_tencent"
    assert saved[0]["data_as_of"] == "2026-09-10T06:34:57.000Z"


def test_preview_does_not_persist_but_reads_official_previous_candidates(monkeypatch):
    repository = PreviewRepository(previous_candidates={"588000.SH"})
    monkeypatch.setattr(
        "finance_analysis.etf_rotation.service.enabled_etfs",  # pragma: allowlist secret
        lambda market: CN_MEMBERS,
    )
    overlay = _overlay_bars({"588000.SH": 1.88, "159915.SZ": 2.66, "510300.SH": 4.55})
    monkeypatch.setattr(
        "finance_analysis.etf_rotation.service.collect_symbol_preview_daily_bars",  # pragma: allowlist secret
        lambda *args, **kwargs: (overlay, "easyquotation_tencent", 3, None),
    )
    monkeypatch.setattr(
        "finance_analysis.etf_rotation.service.save_preview",  # pragma: allowlist secret
        lambda *args, **kwargs: None,
    )
    service = ETFRotationService("CN", repository, market_data=_history_market_data())
    first = service.run_preview(TRADE_DATE)
    second = service.run_preview(TRADE_DATE)
    third = service.run_preview(TRADE_DATE)
    assert first["status"] == second["status"] == third["status"] == "completed"
    assert repository.previous_calls == [TRADE_DATE, TRADE_DATE, TRADE_DATE]
    assert repository.previous_candidates == {"588000.SH"}
    assert repository.market_write_calls == 0
    assert repository.snapshot_write_calls == 0
    assert repository.saved == {}


def test_official_run_after_preview_still_persists(monkeypatch):
    repository = PreviewRepository()
    monkeypatch.setattr(
        "finance_analysis.etf_rotation.service.enabled_etfs",  # pragma: allowlist secret
        lambda market: CN_MEMBERS,
    )
    overlay = _overlay_bars({"588000.SH": 1.88, "159915.SZ": 2.66, "510300.SH": 4.55})
    monkeypatch.setattr(
        "finance_analysis.etf_rotation.service.collect_symbol_preview_daily_bars",  # pragma: allowlist secret
        lambda *args, **kwargs: (overlay, "easyquotation_tencent", 3, None),
    )
    monkeypatch.setattr(
        "finance_analysis.etf_rotation.service.save_preview",  # pragma: allowlist secret
        lambda *args, **kwargs: None,
    )
    service = ETFRotationService("CN", repository, market_data=_history_market_data())
    preview = service.run_preview(TRADE_DATE)
    official = service.run(TRADE_DATE)
    assert preview["status"] == official["status"] == "completed"
    assert repository.market_write_calls == 1
    assert repository.snapshot_write_calls == 1
    assert official["snapshot_count"] == 2
    assert "items" not in official


def test_preview_cache_round_trip_and_set_failure():
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
        "status": "completed",
        "items": [{"code": "588000.SH", "trade_date": TRADE_DATE, "action": "BUY"}],
        "market_snapshot": {"regime": "RISK_ON"},
    }
    save_preview("CN", payload, client=Redis())
    assert stored["key"] == PREVIEW_KEY_TEMPLATE.format(market="CN")
    assert stored["ex"] == 24 * 60 * 60
    loaded = load_preview("CN", client=Redis())
    assert loaded["items"][0]["code"] == "588000.SH"
    assert loaded["market_snapshot"]["regime"] == "RISK_ON"

    class Broken:
        def set(self, key, value, ex=None):
            raise ConnectionError("redis unavailable")

    with pytest.raises(RuntimeError, match="Failed to save ETF Rotation preview for CN") as exc_info:
        save_preview("CN", payload, client=Broken())
    assert isinstance(exc_info.value.__cause__, ConnectionError)


def test_save_preview_raises_when_redis_client_unavailable(monkeypatch):
    import finance_analysis.etf_rotation.preview_cache as cache  # pragma: allowlist secret

    monkeypatch.setattr(cache, "_redis_client", lambda: None)
    with pytest.raises(RuntimeError, match="Redis unavailable"):
        save_preview("US", {"status": "completed"})


def test_preview_task_result_omits_items(monkeypatch):
    from finance_analysis.tasks.celery.jobs.etf_rotation import tasks  # pragma: allowlist secret

    monkeypatch.setattr(tasks, "is_market_open", lambda market, day: True)

    class Service:
        def __init__(self, market):
            self.market = market

        def run_preview(self, requested):
            return {
                "status": "completed",
                "market": "CN",
                "trade_date": requested.isoformat(),
                "preview_time": "2026-09-10T03:05:00+00:00",
                "provider": "easyquotation_tencent",
                "quote_count": 42,
                "universe_size": 42,
                "data_coverage": 1.0,
                "rankable_count": 42,
                "rankable_coverage": 1.0,
                "snapshot_count": 42,
                "candidate_count": 3,
                "candidate_codes": ["588000.SH"],
                "regime": "RISK_ON",
                "elapsed_seconds": 1.2,
                "warnings": [],
                "items": [{"code": "588000.SH"}],
                "market_snapshot": {"regime": "RISK_ON"},
            }

    monkeypatch.setattr(tasks, "ETFRotationService", Service)
    result = tasks._run_preview("CN", "2026-09-10")
    assert "items" not in result
    assert "market_snapshot" not in result
    assert result["status"] == "completed"
    assert result["candidate_codes"] == ["588000.SH"]
    assert result["provider"] == "easyquotation_tencent"


def test_preview_task_skips_non_trading_days(monkeypatch):
    from finance_analysis.tasks.celery.jobs.etf_rotation import tasks  # pragma: allowlist secret

    monkeypatch.setattr(tasks, "is_market_open", lambda market, day: False)
    monkeypatch.setattr(
        tasks,
        "get_market_now",
        lambda market: datetime(2026, 10, 1, 11, 5, tzinfo=ZoneInfo("Asia/Shanghai")),
    )
    with pytest.raises(TaskSkipped, match="不是交易日"):
        tasks._run_preview("CN", None)


def test_preview_api_returns_cached_payload_and_404(monkeypatch):
    from finance_analysis.interfaces.api.v1.endpoints import etf_rotation  # pragma: allowlist secret

    monkeypatch.setattr(
        etf_rotation,
        "load_preview",
        lambda market: {"market": market, "status": "completed", "items": [{"code": "588000.SH"}]},
    )
    payload = etf_rotation.preview(SimpleNamespace(id=1), "CN")
    assert payload["items"][0]["code"] == "588000.SH"

    monkeypatch.setattr(etf_rotation, "load_preview", lambda market: None)
    with pytest.raises(HTTPException) as exc_info:
        etf_rotation.preview(SimpleNamespace(id=1), "US")
    assert exc_info.value.status_code == 404


def test_quote_failure_does_not_write_official_snapshots(monkeypatch):
    repository = PreviewRepository()
    monkeypatch.setattr(
        "finance_analysis.etf_rotation.service.enabled_etfs",  # pragma: allowlist secret
        lambda market: CN_MEMBERS,
    )
    monkeypatch.setattr(
        "finance_analysis.etf_rotation.service.collect_symbol_preview_daily_bars",  # pragma: allowlist secret
        lambda *args, **kwargs: (_ for _ in ()).throw(PreviewQuoteError("easyquotation tencent real failed")),
    )
    saved = []
    monkeypatch.setattr(
        "finance_analysis.etf_rotation.service.save_preview",  # pragma: allowlist secret
        lambda market, payload: saved.append(payload),
    )
    service = ETFRotationService("CN", repository, market_data=SimpleNamespace())
    with pytest.raises(PreviewQuoteError, match="real failed"):
        service.run_preview(TRADE_DATE)
    assert repository.market_write_calls == repository.snapshot_write_calls == 0
    assert saved[0]["status"] == "failed"
    assert saved[0]["items"] == []
    assert saved[0]["data_as_of"] is None


def test_preview_time_is_recorded_after_quotes_and_strategy(monkeypatch):
    repository = PreviewRepository(previous_candidates={"588000.SH"})
    monkeypatch.setattr(
        "finance_analysis.etf_rotation.service.enabled_etfs",  # pragma: allowlist secret
        lambda market: CN_MEMBERS,
    )
    overlay = _overlay_bars({"588000.SH": 1.88, "159915.SZ": 2.66, "510300.SH": 4.55})
    order = []

    def collect(*args, **kwargs):
        order.append("collect")
        return overlay, "easyquotation_tencent", 3, datetime(2026, 9, 10, 6, 34, 57, tzinfo=timezone.utc)

    def now():
        order.append("now")
        return datetime(2026, 9, 10, 6, 35, 11, tzinfo=timezone.utc)

    monkeypatch.setattr(
        "finance_analysis.etf_rotation.service.collect_symbol_preview_daily_bars",  # pragma: allowlist secret
        collect,
    )
    monkeypatch.setattr(
        "finance_analysis.etf_rotation.service.utc_now",  # pragma: allowlist secret
        now,
    )
    monkeypatch.setattr(
        "finance_analysis.etf_rotation.service.save_preview",  # pragma: allowlist secret
        lambda *args, **kwargs: None,
    )
    service = ETFRotationService("CN", repository, market_data=_history_market_data())
    result = service.run_preview(TRADE_DATE)
    assert order == ["collect", "now"]
    assert result["preview_time"] == "2026-09-10T06:35:11.000Z"
    assert result["data_as_of"] == "2026-09-10T06:34:57.000Z"

    order.clear()
    overridden = service.run_preview(
        TRADE_DATE,
        preview_time=datetime(2026, 9, 10, 6, 40, 0, tzinfo=timezone.utc),
    )
    assert order == ["collect"]
    assert overridden["preview_time"] == "2026-09-10T06:40:00.000Z"
    assert overridden["data_as_of"] == "2026-09-10T06:34:57.000Z"


def test_failed_preview_time_is_recorded_after_quote_error(monkeypatch):
    repository = PreviewRepository()
    monkeypatch.setattr(
        "finance_analysis.etf_rotation.service.enabled_etfs",  # pragma: allowlist secret
        lambda market: CN_MEMBERS,
    )
    order = []

    def collect(*args, **kwargs):
        order.append("collect")
        raise PreviewQuoteError("easyquotation tencent real failed")

    def now():
        order.append("now")
        return datetime(2026, 9, 10, 6, 35, 11, tzinfo=timezone.utc)

    monkeypatch.setattr(
        "finance_analysis.etf_rotation.service.collect_symbol_preview_daily_bars",  # pragma: allowlist secret
        collect,
    )
    monkeypatch.setattr("finance_analysis.etf_rotation.service.utc_now", now)  # pragma: allowlist secret
    saved = []
    monkeypatch.setattr(
        "finance_analysis.etf_rotation.service.save_preview",  # pragma: allowlist secret
        lambda market, payload: saved.append(payload),
    )
    service = ETFRotationService("CN", repository, market_data=SimpleNamespace())
    with pytest.raises(PreviewQuoteError, match="real failed"):
        service.run_preview(TRADE_DATE)
    assert order == ["collect", "now"]
    assert saved[0]["preview_time"] == "2026-09-10T06:35:11.000Z"
    assert saved[0]["data_as_of"] is None

# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from finance_analysis.tasks.celery.jobs.us_postmarket_review.models import (
    US_POSTMARKET_BENCHMARKS,
    US_POSTMARKET_SECTOR_ETFS,
)
from finance_analysis.tasks.celery.jobs.us_postmarket_review.reporter import USPostmarketReviewReporter
from finance_analysis.tasks.celery.jobs.us_postmarket_review.domain_service import (
    USPostmarketReviewService,
)
from finance_analysis.tasks.lifecycle import TaskSkipped


TRADING_DATE = datetime(2026, 6, 23, 16, 45, tzinfo=ZoneInfo("America/New_York"))


def _complete_markdown(day: str = "2026-06-23") -> str:
    return f"""# 美股收盘复盘 - {day}

## 1. 今日市场结论
risk_on：基于输入数据判断。

## 2. 主要指数表现
主要指数见表。

## 3. 板块强弱与资金风格
板块数据见输入。

## 4. 自选股表现
自选股表现见输入。

## 5. 今日市场主要驱动
仅引用输入新闻。

## 6. 风险信号
关注回撤风险。

## 7. 下一交易日关注事项
观察 SPY、QQQ 和强弱板块延续。

## 8. 数据说明
基于结构化输入生成。
"""


class FakeDataManager:
    def __init__(self, changes: dict[str, float] | None = None, fail: set[str] | None = None) -> None:
        self.changes = changes or {}
        self.fail = fail or set()

    def get_daily_data(self, symbol: str, start_date=None, end_date=None, days: int = 30):
        if symbol in self.fail:
            raise RuntimeError(f"{symbol} down")
        change = self.changes.get(symbol, 0.0)
        end = TRADING_DATE.date()
        rows = []
        close = 100.0
        for index in range(22):
            day = end - timedelta(days=21 - index)
            pct = 0.1
            if index == 21:
                pct = change
            close = close * (1 + pct / 100)
            rows.append(
                {
                    "date": day.isoformat(),
                    "open": close * 0.99,
                    "high": close * 1.01,
                    "low": close * 0.98,
                    "close": close,
                    "volume": 1000 + index * 10 + (2000 if symbol == "NVDA" and index == 21 else 0),
                    "pct_chg": pct,
                }
            )
        return pd.DataFrame(rows), "FakeSource"


class FakeSearchService:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail

    def search_stock_news(self, *args, **kwargs):
        if self.fail:
            raise RuntimeError("search down")
        return SimpleNamespace(
            results=[
                SimpleNamespace(
                    title="S&P 500 closes higher as tech leads",
                    snippet="Large-cap tech helped US stocks close higher.",
                    url="https://example.com/market",
                    source="Example",
                    published_date="2026-06-23T20:00:00Z",
                )
            ]
        )


class FakeLLM:
    def __init__(self, text: str | None = None, available: bool = True, fail: bool = False) -> None:
        self.text = text
        self.available = available
        self.fail = fail

    def is_available(self) -> bool:
        return self.available

    def complete_text(self, request):
        if self.fail:
            raise RuntimeError("llm down")
        return SimpleNamespace(text=self.text)


class FakeReporter:
    def __init__(self, send_result: bool = True) -> None:
        self.send_result = send_result
        self.send_calls = 0
        self.last_summary = None

    def save_report_file(self, summary):
        return f"/tmp/us_postmarket_review_{summary.trading_date.strftime('%Y%m%d')}.md"

    def record_to_calendar(self, summary):
        return 123

    def send_notification(self, summary, *, send_notification: bool):
        self.last_summary = summary
        if not send_notification:
            return False
        self.send_calls += 1
        if not self.send_result:
            summary.warnings.append("通知发送失败或无可用通知渠道")
        return self.send_result


class EmptyDb:
    class Session:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, stmt):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))

    def get_session(self):
        return self.Session()


def _service(
    *,
    changes: dict[str, float] | None = None,
    fail: set[str] | None = None,
    watch_symbols: list[str] | None = None,
    llm: FakeLLM | None = None,
    reporter: FakeReporter | None = None,
    search: FakeSearchService | None = None,
) -> USPostmarketReviewService:
    default_changes = {
        "SPY": 0.8,
        "QQQ": 1.2,
        "DIA": 0.4,
        "IWM": 0.2,
        "XLK": 1.5,
        "SOXX": 2.0,
        "XLF": -0.3,
        "XLE": -1.1,
        "XLY": 0.9,
        "XLP": -0.1,
        "XLV": 0.1,
        "XLI": 0.2,
        "XLU": -0.2,
        "XLB": -0.4,
        "XLRE": -0.5,
        "AAPL": 1.0,
        "NVDA": 3.0,
        "TSLA": -2.0,
    }
    if changes:
        default_changes.update(changes)
    return USPostmarketReviewService(
        config=SimpleNamespace(report_language="zh", has_search_capability_enabled=lambda: True),
        data_manager=FakeDataManager(default_changes, fail),
        search_service=search or FakeSearchService(),
        llm_client=llm or FakeLLM(_complete_markdown()),
        reporter=reporter or FakeReporter(),
        watch_symbols_provider=lambda: watch_symbols if watch_symbols is not None else ["AAPL", "NVDA", "TSLA"],
        db=EmptyDb(),
    )


@pytest.fixture(autouse=True)
def market_open_after_close(monkeypatch):
    monkeypatch.setattr(
        "finance_analysis.tasks.celery.jobs.us_postmarket_review.domain_service.is_market_open",
        lambda market, day: True,
    )
    monkeypatch.setattr(
        "finance_analysis.tasks.celery.jobs.us_postmarket_review.domain_service.is_market_session_closed",
        lambda market, current_time=None, check_date=None: True,
    )
    monkeypatch.setattr(
        "finance_analysis.tasks.celery.jobs.us_postmarket_review.domain_service.get_effective_trading_date",
        lambda market, current_time=None: current_time.astimezone(ZoneInfo("America/New_York")).date(),
    )


def test_normal_trading_day_after_close_generates_report_and_sends_notification() -> None:
    reporter = FakeReporter()
    summary = _service(reporter=reporter).run(now=TRADING_DATE)

    assert summary.trading_date.isoformat() == "2026-06-23"
    assert summary.market_regime == "risk_on"
    assert summary.benchmark_count == 4
    assert summary.sector_count == 11
    assert summary.watchlist_count == 3
    assert summary.watchlist_up_count == 2
    assert summary.watchlist_down_count == 1
    assert summary.calendar_id == 123
    assert summary.notification_sent is True
    assert summary.fallback_used is False
    assert summary.report_file.endswith("us_postmarket_review_20260623.md")
    assert reporter.send_calls == 1
    json.dumps(summary.to_dict(), ensure_ascii=False)


def test_weekend_or_holiday_skips_without_report(monkeypatch) -> None:
    monkeypatch.setattr(
        "finance_analysis.tasks.celery.jobs.us_postmarket_review.domain_service.is_market_open",
        lambda market, day: False,
    )
    with pytest.raises(TaskSkipped, match="当天不是美股交易日"):
        _service().run(now=TRADING_DATE)


def test_before_close_skips(monkeypatch) -> None:
    monkeypatch.setattr(
        "finance_analysis.tasks.celery.jobs.us_postmarket_review.domain_service.is_market_session_closed",
        lambda market, current_time=None, check_date=None: False,
    )
    with pytest.raises(TaskSkipped, match="美股尚未收盘"):
        _service().run(now=TRADING_DATE.replace(hour=15, minute=59))


def test_dst_and_winter_dates_use_new_york_timezone() -> None:
    summer = datetime(2026, 6, 23, 16, 31, tzinfo=ZoneInfo("America/New_York"))
    winter = datetime(2026, 1, 6, 16, 31, tzinfo=ZoneInfo("America/New_York"))
    service = _service()

    assert service._validate_trading_day_and_close(summer).isoformat() == "2026-06-23"
    assert service._validate_trading_day_and_close(winter).isoformat() == "2026-01-06"


def test_partial_index_failure_degrades_but_completes() -> None:
    summary = _service(fail={"DIA"}, llm=FakeLLM(available=False)).run(now=TRADING_DATE)

    assert summary.benchmark_count == 3
    assert summary.fallback_used is True
    assert any("DIA 行情获取失败" in item for item in summary.warnings)
    assert "AI 分析暂不可用" in summary.report


def test_all_benchmarks_failure_marks_serious_error() -> None:
    with pytest.raises(RuntimeError, match="所有主要指数行情均无法获取"):
        _service(fail=set(US_POSTMARKET_BENCHMARKS)).run(now=TRADING_DATE)


def test_no_watchlist_still_completes() -> None:
    summary = _service(watch_symbols=[]).run(now=TRADING_DATE)

    assert summary.watchlist_count == 0
    assert any("未配置美股自选股" in item for item in summary.warnings)


def test_single_watchlist_symbol_failure_does_not_stop_others() -> None:
    summary = _service(fail={"TSLA"}).run(now=TRADING_DATE)

    assert summary.watchlist_count == 2
    assert summary.watchlist_down_count == 0
    assert any("TSLA 自选股行情获取失败" in item for item in summary.warnings)


def test_sector_rankings_and_relative_returns_are_computed() -> None:
    context = _service()._build_context(TRADING_DATE.date())

    assert [item.symbol for item in context.sector_top3] == ["SOXX", "XLK", "XLY"]
    assert [item.symbol for item in context.sector_bottom3] == ["XLE", "XLRE", "XLB"]
    qqq = next(item for item in context.benchmarks if item.symbol == "QQQ")
    assert qqq.relative_to_spy == pytest.approx(0.4)
    nvda = context.watchlist_summary.gainers[0]
    assert nvda.symbol == "NVDA"
    assert nvda.relative_to_qqq == pytest.approx(1.8)
    assert context.style_bias == "成长"


@pytest.mark.parametrize(
    "llm",
    [
        FakeLLM(available=False),
        FakeLLM(text=""),
        FakeLLM(fail=True),
    ],
)
def test_llm_unavailable_empty_or_exception_uses_fallback(llm: FakeLLM) -> None:
    summary = _service(llm=llm).run(now=TRADING_DATE)

    assert summary.fallback_used is True
    for section in [
        "## 1. 今日市场结论",
        "## 2. 主要指数表现",
        "## 3. 板块强弱与资金风格",
        "## 4. 自选股表现",
        "## 5. 今日市场主要驱动",
        "## 6. 风险信号",
        "## 7. 下一交易日关注事项",
        "## 8. 数据说明",
    ]:
        assert section in summary.report


def test_send_notification_false_does_not_send() -> None:
    reporter = FakeReporter()
    summary = _service(reporter=reporter).run(now=TRADING_DATE, send_notification=False)

    assert summary.notification_sent is False
    assert reporter.send_calls == 0


def test_notification_failure_records_warning() -> None:
    summary = _service(reporter=FakeReporter(send_result=False)).run(now=TRADING_DATE)

    assert summary.notification_sent is False
    assert any("通知发送失败" in item for item in summary.warnings)


def test_news_search_failure_records_warning_and_completes() -> None:
    summary = _service(search=FakeSearchService(fail=True)).run(now=TRADING_DATE)

    assert summary.benchmark_count == 4
    assert any("新闻搜索失败" in item for item in summary.warnings)


def test_reporter_reuses_existing_calendar_entry_and_uses_dedup_key() -> None:
    sent = {}

    class Notifier:
        def save_report_to_file(self, content, filename):
            return f"/tmp/{filename}"

        def send(self, content, **kwargs):
            sent.update(kwargs)
            return True

    class Repo:
        def __init__(self):
            self.updated = False
            self.created = False

        def get_by_type_and_date(self, **kwargs):
            return SimpleNamespace(id=7)

        def update(self, item_id, **kwargs):
            self.updated = True
            return SimpleNamespace(id=item_id)

        def create(self, **kwargs):
            self.created = True
            return SimpleNamespace(id=99)

    repo = Repo()
    reporter = USPostmarketReviewReporter(
        notifier=Notifier(),
        calendar_repo=repo,
        user_repo=SimpleNamespace(ensure_default_admin=lambda: 1),
    )
    summary = _service(reporter=FakeReporter()).run(now=TRADING_DATE, send_notification=False)
    summary.report = _complete_markdown()
    summary.calendar_id = reporter.record_to_calendar(summary)
    summary.notification_sent = reporter.send_notification(summary, send_notification=True)

    assert summary.calendar_id == 7
    assert repo.updated is True
    assert repo.created is False
    assert sent["dedup_key"] == "us_postmarket_review:2026-06-23"
    assert sent["cooldown_key"] == "us_postmarket_review:2026-06-23"


def test_required_symbols_constants_are_complete() -> None:
    assert set(US_POSTMARKET_BENCHMARKS) == {"SPY", "QQQ", "DIA", "IWM"}
    assert {"XLK", "SOXX", "XLF", "XLE", "XLRE"}.issubset(US_POSTMARKET_SECTOR_ETFS)

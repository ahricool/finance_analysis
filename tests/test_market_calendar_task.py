"""Dual-provider orchestration, Universe filtering, and notification regression tests."""

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from finance_analysis.database.repositories.market_calendar_event import MarketCalendarEventRepo
from finance_analysis.integrations.market_data.calendar import CalendarFetchResult
from finance_analysis.tasks.celery.jobs.market_calendar_sync.domain_service import MarketCalendarSyncService
from tests.test_market_calendar_event_repo import CalendarDB, event

NOW = datetime(2026, 6, 18, 12, tzinfo=timezone.utc)


def source(events=(), errors=()):
    def fetch(start, end, market, symbols=()):
        return CalendarFetchResult(
            events=[item for item in events if item["market"] == market],
            errors=list(errors),
            pages_succeeded=1,
            fetched=len(events),
        )

    obj = MagicMock()
    obj.fetch_earnings_calendar.side_effect = fetch
    obj.fetch_macro_calendar.return_value = CalendarFetchResult(pages_succeeded=1)
    return obj


@pytest.fixture
def setup_service(monkeypatch):
    monkeypatch.setattr(
        "finance_analysis.database.repositories.watch_list.get_watch_list_codes_by_market", lambda market: []
    )
    repo = MarketCalendarEventRepo(db=CalendarDB())
    resolver = MagicMock()
    resolver.resolve_universe.side_effect = lambda key: tuple(
        SimpleNamespace(code=value) for value in (["NVDA.US"] if key == "us_sp500" else ["600519.SH"])
    )
    notifier = MagicMock()
    notifier.send.return_value = True

    def build(yahoo, lb):
        return MarketCalendarSyncService(
            sources={"yfinance": yahoo, "longbridge": lb},
            repo=repo,
            universe_resolver=resolver,
            notifier_factory=lambda: notifier,
        )

    return build, repo, resolver, notifier


def test_both_sources_both_markets_and_macro_always_requested(setup_service):
    build, repo, resolver, notifier = setup_service
    yahoo = source([event(), event(symbol="OUTSIDE.US")])
    lb = source([event("longbridge", market_session="amc"), event("longbridge", symbol="600519.SH", market="CN")])
    result = build(yahoo, lb).run(NOW)
    assert result.inserted_count == 2 and result.merged_count == 2
    assert result.notification_sent_count == 2
    assert not result.all_interfaces_failed
    assert set(result.source_stats) == {
        f"{p}:{t}:{m}"
        for p in ("yfinance", "longbridge")
        for t, m in (("earnings", "US"), ("earnings", "CN"), ("macro", "US"))
    }
    for adapter in (yahoo, lb):
        assert adapter.fetch_earnings_calendar.call_count == 2
        adapter.fetch_macro_calendar.assert_called_once()
    assert [call.args[0] for call in resolver.resolve_universe.call_args_list] == ["us_sp500", "cn_csi300"]
    rows = repo.list_events_by_date_range(date(2026, 6, 18), date(2026, 7, 18))
    assert {row.symbol for row in rows} == {"NVDA.US", "600519.SH"}
    assert "14 天" not in notifier.send.call_args.args[0]
    assert "2026-07-18" in notifier.send.call_args.args[0]


def test_partial_provider_and_cn_failures_do_not_discard_us(setup_service):
    build, _, _, _ = setup_service
    yahoo = source([event()], errors=["offset=100 failed"])
    lb = source()
    lb.fetch_earnings_calendar.side_effect = RuntimeError("unavailable")
    summary = build(yahoo, lb).run(NOW)
    assert summary.inserted_count == 1 and summary.errors
    assert not summary.all_interfaces_failed
    assert summary.source_stats["yfinance:earnings:CN"]["accepted"] == 0
    assert summary.source_stats["longbridge:earnings:US"]["errors"] == 1


def test_empty_success_is_not_failure_but_all_core_sources_down_is_failure(setup_service):
    build, _, _, _ = setup_service
    yahoo, lb = source(), source()
    assert not build(yahoo, lb).run(NOW).all_interfaces_failed
    for adapter in (yahoo, lb):
        adapter.fetch_earnings_calendar.side_effect = RuntimeError("down")
        adapter.fetch_macro_calendar.side_effect = RuntimeError("down")
    assert build(yahoo, lb).run(NOW).all_interfaces_failed


def test_universe_failure_isolated_and_never_unrestricted_earnings(setup_service):
    build, _, resolver, _ = setup_service
    resolver.resolve_universe.side_effect = ValueError("missing Universe")
    summary = build(source([event()]), source()).run(NOW)
    assert summary.inserted_count == 0
    assert any("Universe" in error for error in summary.errors)


def test_enrichment_silent_date_and_session_changes_notify_once(setup_service):
    build, repo, _, notifier = setup_service
    first = build(source([event()]), source()).run(NOW)
    assert first.notification_sent_count == 1
    second = build(source([event(eps_estimate=1.2)]), source([event("longbridge", currency="USD")])).run(NOW)
    assert second.notification_sent_count == 0
    third = build(
        source([event(event_date="2026-06-19", market_session="bmo")]),
        source([event("longbridge", market_session="amc")]),
    ).run(NOW)
    assert third.inserted_count == 0 and third.notification_sent_count == 1
    assert notifier.send.call_count == 2
    assert len(repo.list_events_by_date_range(date(2026, 6, 18), date(2026, 7, 18))) == 1


def test_failed_send_does_not_mark_notified(setup_service):
    build, repo, _, notifier = setup_service
    notifier.send.return_value = False
    summary = build(source([event()]), source()).run(NOW)
    assert summary.notification_sent_count == 0
    assert repo.list_events_by_date(date(2026, 6, 20))[0].notified_at is None


def test_single_write_error_does_not_stop_other_market(setup_service):
    build, repo, _, _ = setup_service
    original = repo.upsert_event

    def write(data, **kwargs):
        if data["market"] == "US":
            raise ValueError("bad event")
        return original(data, **kwargs)

    repo.upsert_event = write
    summary = build(source([event(), event(market="CN", symbol="600519.SH")]), source()).run(NOW)
    assert summary.inserted_count == 1 and not summary.all_writes_failed


def test_cn_available_data_survives_all_us_failures(setup_service):
    build, _, _, _ = setup_service
    yahoo, lb = source(), source()

    def fetch(start, end, market, symbols=()):
        if market == "US":
            raise ValueError("US down")
        return CalendarFetchResult(events=[event(market="CN", symbol="600519.SH")], pages_succeeded=1, fetched=1)

    yahoo.fetch_earnings_calendar.side_effect = fetch
    lb.fetch_earnings_calendar.side_effect = RuntimeError("down")
    for adapter in (yahoo, lb):
        adapter.fetch_macro_calendar.side_effect = RuntimeError("macro down")
    summary = build(yahoo, lb).run(NOW)
    assert summary.inserted_count == 1 and not summary.all_interfaces_failed

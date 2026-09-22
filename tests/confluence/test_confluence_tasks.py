"""Formal confluence uses only completed CN/US sessions."""

from datetime import datetime, date
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from finance_analysis.tasks.celery.jobs.confluence import tasks
from finance_analysis.tasks.lifecycle import TaskSkipped


@pytest.mark.parametrize("market,zone,hour", [("CN", "Asia/Shanghai", 10), ("US", "America/New_York", 13)])
def test_intraday_default_uses_previous_session_and_explicit_today_skips(monkeypatch, market, zone, hour):
    now = datetime(2026, 9, 22, hour, tzinfo=ZoneInfo(zone))
    monkeypatch.setattr(tasks, "get_market_now", lambda *_: now)
    calls = []
    monkeypatch.setattr(tasks, "ConfluenceService", lambda: SimpleNamespace(run=lambda m, d: calls.append((m, d))))
    tasks._run(market)
    assert calls == [(market, date(2026, 9, 21))]
    with pytest.raises(TaskSkipped):
        tasks._run(market, "2026-09-22")
    assert len(calls) == 1


@pytest.mark.parametrize("market,zone,hour", [("CN", "Asia/Shanghai", 16), ("US", "America/New_York", 17)])
def test_closed_today_and_historical_session_are_allowed(monkeypatch, market, zone, hour):
    now = datetime(2026, 9, 22, hour, tzinfo=ZoneInfo(zone))
    monkeypatch.setattr(tasks, "get_market_now", lambda *_: now)
    calls = []
    monkeypatch.setattr(tasks, "ConfluenceService", lambda: SimpleNamespace(run=lambda m, d: calls.append((m, d))))
    tasks._run(market)
    tasks._run(market, "2026-09-22")
    tasks._run(market, "2026-09-21")
    assert calls == [(market, date(2026, 9, 22)), (market, date(2026, 9, 22)), (market, date(2026, 9, 21))]

"""PR #386 business regressions, using only injected data and local SQLite/Redis fakes."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from billiard.exceptions import SoftTimeLimitExceeded

from finance_analysis.database.models.task import TaskRecord
from finance_analysis.integrations.options.models import OptionChain
from finance_analysis.integrations.options.providers import YahooOptionsProvider
from finance_analysis.integrations.options.service import OptionsDataService
from finance_analysis.options_intelligence.engine import analyze
from finance_analysis.options_intelligence.preview_cache import load_preview, save_preview
from finance_analysis.options_intelligence.service import OptionsIntelligenceService
from finance_analysis.tasks.celery.jobs.options_intelligence.tasks import scan_outcome, scan_options_intraday
from finance_analysis.tasks.lifecycle import TaskExecutionStatus, _json_summary, MAX_RESULT_CHARS
from .test_preview_history import Cache, counts, service
from . import test_api
from finance_analysis.options_intelligence.views import scan_view

client = test_api.client


def utc(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "stamp,valid",
    [
        ("2026-10-07T20:30", True),  # ordinary close + 30m, EDT
        ("2026-10-07T20:29", False),
        ("2026-11-27T18:30", True),  # Black Friday 13:00 EST close
        ("2026-11-27T18:29", False),
        ("2026-10-10T22:00", False),  # Saturday
        ("2026-10-11T22:00", False),  # Sunday
        ("2026-07-03T22:00", False),  # Independence Day observed
        ("2026-10-08T13:00", False),  # next session before open
    ],
)
def test_official_requires_today_real_session(repository, observation, config, stamp, valid):
    now = utc(stamp)
    row = observation.model_copy(update={"expiration": now.date() + timedelta(days=30), "volume_date": now.date()})
    engine = service(repository, row, now, config, Cache())
    if valid:
        engine.scan(["AAPL.US"], now, view="official")
        first = repository.latest("AAPL.US", now.date())
        assert first is not None
        engine.run("AAPL.US", now + timedelta(minutes=1), view="official")
        assert repository.latest("AAPL.US", now.date()) == first
    else:
        for run in (
            lambda: engine.run("AAPL.US", now, view="official"),
            lambda: engine.scan(["AAPL.US"], now, view="official"),
        ):
            with pytest.raises(ValueError, match="30 minutes"):
                run()
        engine.market.get_option_chain.assert_not_called()
        assert counts(repository) == [0] * 5


@pytest.mark.parametrize(
    "put,call,stale,source",
    [
        (0, 0, False, "alpaca"),
        (200, None, False, "alpaca"),
        (200, 400, True, "alpaca"),
        (600, 400, False, "yfinance"),
        (0, 400, False, "yfinance"),
    ],
)
def test_volume_fallback_requires_computable_complete_ratio(observation, now, config, put, call, stale, source):
    yahoo = [
        observation.model_copy(update={"data_source": "yfinance", "feed_type": "delayed", "volume": put}),
        observation.model_copy(
            update={
                "symbol": "AAPL261106C00100000",
                "option_type": "call",
                "data_source": "yfinance",
                "feed_type": "delayed",
                "volume": call,
            }
        ),
    ]
    if stale:
        for row in yahoo:
            row.volume_date = now.date() - timedelta(days=1)
    alpaca = [
        observation.model_copy(update={"volume": 200}),
        observation.model_copy(update={"symbol": "AAPL261106C00100000", "option_type": "call", "volume": 400}),
    ]
    result = analyze(
        OptionChain(symbol="AAPL.US", observed_at=now, observations=yahoo + alpaca),
        now.date(),
        now,
        [],
        "daily",
        config,
    )
    assert result["volume_source"] == source
    assert result["put_call_volume_ratio"] == (put / call if source == "yfinance" else 0.5)
    coverage = result["coverage"]["put_call_volume"][2]
    assert coverage["source"] == source and coverage["call_valid_fraction"] == 1


def test_no_volume_source_does_not_invent_ratio(observation, now, config):
    row = observation.model_copy(update={"volume": 0})
    call = row.model_copy(update={"symbol": "AAPL261106C00100000", "option_type": "call"})
    result = analyze(
        OptionChain(symbol="AAPL.US", observed_at=now, observations=[row, call]), now.date(), now, [], "daily", config
    )
    assert result["put_call_volume_ratio"] is None
    assert result["scores"]["bearish_demand"]["value"] is None


def test_preview_merge_failure_recovery_and_atomic_detail(now):
    cache = Cache()

    def publish(items=(), failures=(), merge=True, stamp=now):
        save_preview(
            {"trade_date": stamp.date().isoformat(), "items": list(items), "failures": list(failures)},
            now=stamp,
            client=cache,
            merge=merge,
        )

    a = {"symbol": "AAPL.US", "computed_at": now.isoformat(), "status": "ready", "scores": None}
    b = {**a, "symbol": "MSFT.US"}
    publish([a, b], [{"symbol": "FAIL.US", "reason": "old failure"}], False)
    publish(failures=[{"symbol": "AAPL.US", "reason": "timeout"}])
    manifest = load_preview(client=cache, now=now)
    detail = load_preview(client=cache, now=now, symbol="AAPL.US")
    summary = next(r for r in manifest["items"] if r["symbol"] == "AAPL.US")
    assert detail["computed_at"] == summary["computed_at"] == a["computed_at"]
    assert detail["refresh_status"] == summary["refresh_status"] == "failed"
    assert detail["refresh_reason"] == "timeout"
    assert {r["symbol"] for r in manifest["failures"]} == {"AAPL.US", "FAIL.US"}
    publish([{**a, "computed_at": (now + timedelta(minutes=1)).isoformat()}])
    manifest = load_preview(client=cache, now=now)
    assert [r["symbol"] for r in manifest["failures"]] == ["FAIL.US"]
    assert "refresh_status" not in load_preview(client=cache, now=now, symbol="AAPL.US")
    assert next(r for r in manifest["items"] if r["symbol"] == "MSFT.US") == scan_view(b)
    publish([b], [{"symbol": "NEW.US", "reason": "new failure"}], False)
    assert load_preview(client=cache, now=now)["items"] == [scan_view(b)]
    assert load_preview(client=cache, now=now, symbol="AAPL.US") is None
    next_day = now + timedelta(days=1)
    publish([{**a, "computed_at": next_day.isoformat()}], stamp=next_day)
    manifest = load_preview(client=cache, now=next_day)
    assert manifest["failures"] == [] and [r["symbol"] for r in manifest["items"]] == ["AAPL.US"]


@pytest.mark.parametrize(
    "stamp,seconds_per_stock,expected",
    [
        ("2026-10-07T19:30", 50, 24),  # 15:30 preview cannot keep scanning until 17:00
        ("2026-11-27T17:50", 60, 10),  # 12:50 -> real early close at 13:00
    ],
)
def test_serial_100_stock_budget_retains_completed_results(
    monkeypatch, config, stamp, seconds_per_stock, expected, caplog
):
    from finance_analysis.options_intelligence import service as module

    clock = [utc(stamp), 0]
    monkeypatch.setattr(module, "utc_now", lambda: clock[0])
    monkeypatch.setattr(module, "monotonic", lambda: clock[1])
    repo = Mock()
    repo.monitored_symbols.return_value = [f"TEST{i}.US" for i in range(100)]
    cache = Cache()
    engine = OptionsIntelligenceService(repo, Mock(), config, preview_client=cache)

    def run(symbol, *args, **kwargs):
        row = {"symbol": symbol, "status": "ready", "computed_at": clock[0].isoformat()}
        clock[0] += timedelta(seconds=seconds_per_stock)
        clock[1] += seconds_per_stock
        return row

    engine.run = Mock(side_effect=run)
    with caplog.at_level("INFO"):
        result = engine.scan(view="preview")
    assert len(result["results"]) == expected
    assert result["unfinished_count"] == 100 - expected
    assert len(load_preview(client=cache, now=clock[0])["items"]) == expected
    assert f"success={expected} failed=0 unfinished={100 - expected}" in caplog.text
    assert scan_outcome(result).status == TaskExecutionStatus.PARTIAL
    # The same service can proceed with today's official session, without preview budget restriction.
    clock[0] = utc(stamp).replace(hour=22)
    assert engine.scan(["TEST0.US"], view="official")["unfinished_count"] == 0


def test_soft_budget_publishes_partial_and_limits_worker(repository, observation, now, config):
    intraday = now.replace(hour=18)
    cache = Cache()
    engine = service(repository, observation, intraday, config, cache)
    engine.run = Mock(
        side_effect=[
            {"symbol": "AAPL.US", "status": "ready", "computed_at": intraday.isoformat()},
            SoftTimeLimitExceeded(),
        ]
    )
    result = engine.scan(["AAPL.US", "MSFT.US"], intraday, view="preview")
    assert result["unfinished_count"] == 1 and result["failed_count"] == 0
    assert load_preview(client=cache, now=intraday)["items"][0]["symbol"] == "AAPL.US"
    assert scan_options_intraday.soft_time_limit == 1200
    assert scan_options_intraday.time_limit == 1260


@pytest.mark.parametrize("stage", ["yahoo", "expiry", "alpaca", "cache", "reference"])
def test_options_fallback_does_not_swallow_worker_soft_limit(now, config, stage):
    yahoo, alpaca, cache = Mock(), Mock(), Mock()
    cache.get.return_value = None
    yahoo.fetch.return_value = OptionChain(symbol="AAPL.US", observed_at=now)
    loader = Mock(return_value=SimpleNamespace(data={}))
    if stage == "expiry":
        ticker = SimpleNamespace(options=["2026-11-06"], option_chain=Mock(side_effect=SoftTimeLimitExceeded()))
        yahoo = YahooOptionsProvider(lambda _: ticker)
    elif stage == "reference":
        loader.side_effect = SoftTimeLimitExceeded()
    elif stage == "cache":
        cache.get.side_effect = SoftTimeLimitExceeded()
    else:
        getattr(yahoo if stage == "yahoo" else alpaca, "fetch").side_effect = SoftTimeLimitExceeded()
    with pytest.raises(SoftTimeLimitExceeded):
        OptionsDataService(yahoo, alpaca, cache, config, loader).fetch("AAPL.US", now)


def add_task(repository, now, results, *, uid=None, day=None, view="official", task_id="scan", failed_count=None):
    payload = {
        "view": view,
        "trade_date": (day or now.date()).isoformat(),
        "results": results,
        "failed_count": failed_count if failed_count is not None else sum(r["status"] == "failed" for r in results),
        "total_count": len(results),
        "unfinished_count": 0,
        "status_counts": {},
    }
    with repository.db.session_scope() as session:
        session.add(
            TaskRecord(
                task_id=task_id,
                task_type="options_intelligence",
                source="celery_manual",
                uid=uid,
                status="partial",
                started_at=now,
                result=_json_summary(payload, limit=MAX_RESULT_CHARS),
            )
        )


def test_official_failure_status_is_date_and_user_scoped(client, repository, now):
    repository.monitored_symbols = lambda uid: ["AAPL.US", "MSFT.US", "UNKNOWN.US"]
    failure = {"symbol": "AAPL.US", "status": "failed", "reason": "provider timeout"}
    add_task(repository, now, [failure], uid=7)
    add_task(
        repository,
        now + timedelta(minutes=1),
        [{**failure, "reason": "other user's failure"}],
        uid=8,
        task_id="private",
    )
    add_task(
        repository,
        now + timedelta(minutes=2),
        [{**failure, "symbol": "MSFT.US"}],
        uid=7,
        day=now.date() - timedelta(days=1),
        task_id="wrong-date",
    )
    response = client.get(f"/api/v1/options-intelligence?trade_date={now.date()}").json()
    assert response["items"][0]["status"] == "failed"
    assert response["items"][0]["limitations"] == ["provider timeout"]
    assert all(r["status"] == "not_scanned" for r in response["items"][1:])
    assert response["failed_count"] == 1 and "TaskRecord" in response["failure_source"]
    assert repository.scan(["AAPL.US"], now.date() - timedelta(days=1), uid=7)[0]["status"] == "not_scanned"
    add_task(
        repository, now + timedelta(minutes=3), [{"symbol": "AAPL.US", "status": "ready"}], uid=7, task_id="recovery"
    )
    assert repository.scan(["AAPL.US"], now.date(), uid=7)[0]["status"] == "not_scanned"


def test_task_truncation_is_unknown_not_invented_failure(repository, now):
    results = [{"symbol": f"TEST{i}.US", "status": "failed", "reason": "timeout"} for i in range(100)]
    add_task(repository, now, results)
    rows = repository.scan(["TEST0.US", "TEST99.US"], now.date())
    assert rows[0]["status"] == "failed" and rows[1]["status"] == "not_scanned"
    assert (
        scan_outcome({"failed_count": 100, "total_count": 100, "unfinished_count": 0}).status
        == TaskExecutionStatus.FAILED
    )


def test_failed_only_date_is_selectable_without_cross_user_or_session_leak(client, repository, now):
    repository.monitored_symbols = lambda uid: ["AAPL.US"]
    failure = {"symbol": "AAPL.US", "status": "failed", "reason": "unavailable"}
    add_task(repository, now, [failure], uid=7)
    add_task(repository, now - timedelta(days=1), [failure], uid=8, task_id="private-history")
    add_task(repository, now + timedelta(minutes=1), [failure], uid=7, view="preview", task_id="preview")
    response = client.get("/api/v1/options-intelligence").json()
    assert response["available_dates"] == [now.date().isoformat()]
    assert response["trade_date"] == now.date().isoformat()
    assert response["items"][0]["status"] == "failed"
    assert response["latest_task_summary"] == {"failed_count": 1, "total_count": 1}


def test_truncated_task_uses_total_counts_without_inventing_symbol_state(client, repository, now):
    results = [{"symbol": f"TEST{i}.US", "status": "failed", "reason": "unavailable"} for i in range(100)]
    add_task(repository, now, results)
    repository.monitored_symbols = lambda uid: ["TEST0.US", "TEST99.US"]
    response = client.get(f"/api/v1/options-intelligence?trade_date={now.date()}").json()
    assert response["failed_count"] == 1
    assert response["latest_task_summary"] == {"failed_count": 100, "total_count": 100}
    assert response["items"][1]["status"] == "not_scanned"
    earlier = client.get(f"/api/v1/options-intelligence?trade_date={now.date() - timedelta(days=1)}").json()
    assert earlier["latest_task_summary"] is None and earlier["failed_count"] == 0


def test_all_failed_scan_is_persisted_as_failed_outcome_and_releases_mutex(
    monkeypatch, repository, observation, now, config
):
    from finance_analysis.options_intelligence import service as module
    from finance_analysis.tasks import lifecycle
    from finance_analysis.tasks.celery.jobs.options_intelligence import tasks

    engine = service(repository, observation, now, config, Cache())
    engine.market.get_option_chain.return_value = OptionChain(symbol="AAPL.US", observed_at=now, errors=["missing"])
    monkeypatch.setattr(module, "utc_now", lambda: now)
    monkeypatch.setattr(tasks, "OptionsIntelligenceService", lambda **kwargs: engine)
    monkeypatch.setattr(tasks, "get_options_config", lambda: config)
    tracking, lock = Mock(), Mock()
    lock.acquire.return_value = True
    monkeypatch.setattr(lifecycle, "get_task_lifecycle_service", lambda: tracking)
    monkeypatch.setattr(lifecycle, "PostgreSQLAdvisoryLock", lambda *args, **kwargs: lock)
    result = tasks.options_request.run(symbol="AAPL.US", view="official", owner_uid=7)
    assert result["trade_date"] == now.date().isoformat() and result["failed_count"] == 1
    outcome = tracking.mark_outcome.call_args.kwargs
    assert outcome["outcome"].status == TaskExecutionStatus.FAILED
    assert outcome["result"]["results"][0]["symbol"] == "AAPL.US"
    tracking.mark_completed.assert_not_called()
    lock.release.assert_called_once()


def test_all_failed_preview_still_reports_redis_publication_error(repository, observation, now, config):
    intraday = now.replace(hour=18)
    cache = Mock()
    cache.get.return_value = None
    cache.pipeline.side_effect = RuntimeError("redis down")
    engine = service(repository, observation, intraday, config, cache)
    engine.market.get_option_chain.return_value = OptionChain(symbol="AAPL.US", observed_at=intraday)
    with pytest.raises(RuntimeError, match="redis down"):
        engine.scan(["AAPL.US"], intraday, view="preview")
    assert counts(repository) == [0] * 5


def test_manual_preview_limits_and_mode_are_frozen_before_queue_delay(client, monkeypatch):
    from finance_analysis.core import time
    from finance_analysis.tasks.celery.jobs.options_intelligence.tasks import options_request

    send = Mock(return_value=SimpleNamespace(id="preview"))
    monkeypatch.setattr(options_request, "apply_async", send)
    monkeypatch.setattr(time, "utc_now", lambda: utc("2026-10-07T19:30"))
    assert client.post("/api/v1/options-intelligence/AAPL.US/refresh").status_code == 202
    args = send.call_args.kwargs
    assert args["kwargs"]["view"] == "preview" and args["soft_time_limit"] == 1200 and args["time_limit"] == 1260
    assert client.post("/api/v1/options-intelligence/AAPL.US/refresh", json={"view": "official"}).status_code == 202
    assert "soft_time_limit" not in send.call_args.kwargs


def test_100_stock_scan_replays_existing_fixture_offline(now, observation, config):
    intraday = now.replace(hour=18)
    repo, market, cache = Mock(), Mock(), Cache()
    repo.monitored_symbols.return_value = [f"TEST{i}.US" for i in range(100)]
    repo.history.return_value = []
    market.get_daily_bars.return_value = SimpleNamespace(data={})

    def chain(symbol, **kwargs):
        return OptionChain(
            symbol=symbol,
            observed_at=intraday,
            observations=[
                observation.model_copy(
                    update={"underlying_symbol": symbol, "observed_at": intraday, "quote_timestamp": intraday}
                )
            ],
        )

    market.get_option_chain.side_effect = chain
    result = OptionsIntelligenceService(repo, market, config, preview_client=cache).scan(now=intraday, view="preview")
    assert result["total_count"] == len(result["results"]) == 100
    assert result["unfinished_count"] == result["failed_count"] == 0
    assert len(load_preview(client=cache, now=intraday)["items"]) == 100
    repo.save.assert_not_called()
    assert all(call.kwargs["source_policy"] == "db_only" for call in market.get_daily_bars.call_args_list)


def test_preview_checkpoint_survives_abort_of_later_symbol(repository, observation, now, config):
    intraday, cache = now.replace(hour=18), Cache()
    engine = service(repository, observation, intraday, config, cache)
    repository.monitored_symbols = lambda: ["AAPL.US", "MSFT.US"]
    engine.run = Mock(
        side_effect=[
            {"symbol": "AAPL.US", "status": "ready", "computed_at": intraday.isoformat()},
            SystemExit("worker terminated"),
        ]
    )
    with pytest.raises(SystemExit):
        engine.scan(now=intraday, view="preview")
    assert load_preview(client=cache, now=intraday)["items"][0]["symbol"] == "AAPL.US"
    assert load_preview(client=cache, now=intraday, symbol="AAPL.US")["status"] == "ready"


def test_official_round_never_moves_into_later_session(monkeypatch, repository, observation, now, config):
    from finance_analysis.options_intelligence import service as module

    current = [now]
    monkeypatch.setattr(module, "utc_now", lambda: current[0])
    engine = service(repository, observation, now, config, Cache())

    def run(symbol, *args, **kwargs):
        current[0] += timedelta(days=1)
        return {"symbol": symbol, "status": "ready"}

    engine.run = Mock(side_effect=run)
    result = engine.scan(["AAPL.US", "MSFT.US"], view="official")
    assert engine.run.call_count == 1
    assert result["trade_date"] == now.date().isoformat() and result["unfinished_count"] == 1


def test_preview_publication_cannot_relabel_previous_day(now, repository, observation, config):
    engine = service(repository, observation, now, config, Cache())
    with pytest.raises(ValueError, match="previous session"):
        engine._publish_preview([], now + timedelta(days=1), trade_date=now.date())

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from finance_analysis.options_intelligence.service import session_context, OptionsIntelligenceService
from finance_analysis.integrations.options.models import OptionChain


def test_holidays_early_close_and_dst():
    _, phase, opened, closed = session_context(datetime(2026, 11, 27, 18, 30, tzinfo=timezone.utc))
    assert phase == "daily" and closed.hour == 18  # Black Friday 13:00 EST
    _, phase, opened, _ = session_context(datetime(2026, 7, 6, 14, tzinfo=timezone.utc))
    assert phase == "intraday" and opened.hour == 13  # EDT
    day, phase, _, _ = session_context(datetime(2026, 7, 3, 16, tzinfo=timezone.utc))
    assert day < date(2026, 7, 3) and phase == "daily"
    day, phase, _, _ = session_context(datetime(2026, 10, 7, 13, tzinfo=timezone.utc))
    assert day == date(2026, 10, 6)  # before open


def test_orchestration_uses_db_history_and_warms_up(repository, observation, now, config):
    market = Mock()
    market.get_option_chain.return_value = OptionChain(symbol="AAPL.US", observed_at=now, observations=[observation])
    market.get_daily_bars.return_value = SimpleNamespace(data={})
    result = OptionsIntelligenceService(repository, market, config).run("AAPL", now)
    assert result["status"] == "warming_up"
    assert market.get_daily_bars.call_args.kwargs["source_policy"] == "db_only"
    assert repository.latest("AAPL.US")["symbol"] == "AAPL.US"


def test_no_observations_never_overwrites_good_state(repository, observation, now, config):
    market = Mock()
    market.get_option_chain.return_value = OptionChain(symbol="AAPL.US", observed_at=now, observations=[observation])
    market.get_daily_bars.return_value = SimpleNamespace(data={})
    service = OptionsIntelligenceService(repository, market, config)
    service.run("AAPL", now)
    old = repository.latest("AAPL.US")
    market.get_option_chain.return_value = OptionChain(symbol="AAPL.US", observed_at=now, errors=["yfinance:failure"])
    with pytest.raises(ValueError, match="unavailable"):
        service.run("AAPL", now + timedelta(minutes=30))
    assert repository.latest("AAPL.US") == old


def test_mixed_volume_dates_keep_valid_chain(repository, observation, now, config):
    market = Mock()
    stale = observation.model_copy(update={"volume_date": now.date() - timedelta(days=1), "volume": 100000})
    market.get_option_chain.return_value = OptionChain(symbol="AAPL.US", observed_at=now, observations=[stale])
    market.get_daily_bars.return_value = SimpleNamespace(data={})
    result = OptionsIntelligenceService(repository, market, config).run("AAPL", now)
    assert result["status"] == "warming_up"
    latest = repository.latest("AAPL.US")
    assert latest["contracts"][0]["volume_oi"] is None
    assert "volume_session_unknown_or_stale" in latest["contracts"][0]["limitations"]


def test_explanation_is_structured_cached_and_uses_existing_llm(repository, observation, now, config):
    from finance_analysis.llm import LLMResult
    import json

    market = Mock()
    market.get_option_chain.return_value = OptionChain(symbol="AAPL.US", observed_at=now, observations=[observation])
    market.get_daily_bars.return_value = SimpleNamespace(data={})
    fields = dict(
        why_it_matters="异常成交",
        possible_catalysts=[],
        protection_vs_direction="无法确认净开仓",
        alternative_explanations=[],
        data_limits=["无逐笔方向"],
        trading_risks=["点差"],
    )
    client = Mock()
    client.complete_text.return_value = LLMResult(text=json.dumps(fields), backend="api", model="test")
    repository.context = lambda *args: {"news": [], "calendar": []}
    service = OptionsIntelligenceService(repository, market, config, client)
    service.run("AAPL", now)
    assert service.explain("AAPL") == fields
    assert service.explain("AAPL") == fields
    assert client.complete_text.call_count == 1
    assert client.complete_text.call_args.args[0].web_search is False


def test_historical_explanation_does_not_use_context_or_prices_after_snapshot(repository, observation, now, config):
    import json
    from finance_analysis.llm import LLMResult

    market = Mock()
    market.get_option_chain.return_value = OptionChain(symbol="AAPL.US", observed_at=now, observations=[observation])
    market.get_daily_bars.return_value = SimpleNamespace(data={})
    client = Mock()
    client.complete_text.return_value = LLMResult(
        text=json.dumps(
            dict(
                why_it_matters="",
                possible_catalysts=[],
                protection_vs_direction="",
                alternative_explanations=[],
                data_limits=[],
                trading_risks=[],
            )
        ),
        backend="api",
        model="test",
    )
    repository.context = Mock(return_value={"news": [], "calendar": []})
    engine = OptionsIntelligenceService(repository, market, config, client)
    engine.run("AAPL.US", now, view="official")
    engine.explain("AAPL.US", now.date())
    assert repository.context.call_args.args[1] == now
    assert market.get_daily_bars.call_args.args[2] == now.date()


def test_auto_explanation_is_once_per_snapshot_session(repository, observation, config):
    from dataclasses import replace

    now = datetime(2026, 10, 7, 22, tzinfo=timezone.utc)
    previous_day = now.date()
    row = observation.model_copy(update={"observed_at": now, "volume_date": previous_day, "volume": 1000})
    market = Mock()
    market.get_option_chain.return_value = OptionChain(symbol="AAPL.US", observed_at=now, observations=[row])
    market.get_daily_bars.return_value = SimpleNamespace(data={})
    repository.analysis_history = lambda symbol: [{"created_at": now, "trade_date": previous_day}]
    service = OptionsIntelligenceService(repository, market, replace(config, auto_explain=True))
    service.explain = Mock()
    service.run("AAPL", now)
    service.explain.assert_not_called()


@pytest.mark.parametrize("missing_price", [False, True])
def test_scan_batches_daily_bars_and_only_quotes_missing_prices(repository, observation, now, config, missing_price):
    market = Mock()

    def chain(symbol, now=None):
        row = observation.model_copy(
            update={"underlying_symbol": symbol, "underlying_price": None if missing_price else 100}
        )
        return OptionChain(symbol=symbol, observed_at=now, observations=[row])

    market.get_option_chain.side_effect = chain
    market.get_realtime_quotes.return_value = SimpleNamespace(data={})
    market.get_daily_bars.return_value = SimpleNamespace(data={})
    OptionsIntelligenceService(repository, market, config).scan(["AAPL", "MSFT"], now=now)
    if missing_price:
        assert [call.args[0] for call in market.get_realtime_quotes.call_args_list] == [["AAPL.US"], ["MSFT.US"]]
    else:
        market.get_realtime_quotes.assert_not_called()
    market.get_daily_bars.assert_called_once()
    assert list(market.get_daily_bars.call_args.args[0]) == ["AAPL.US", "MSFT.US"]
    assert market.get_daily_bars.call_args.kwargs["source_policy"] == "db_only"


def test_scan_preserves_soft_time_limit_during_prefetch(repository, now, config):
    from billiard.exceptions import SoftTimeLimitExceeded

    market = Mock()
    market.get_daily_bars.side_effect = SoftTimeLimitExceeded()
    with pytest.raises(SoftTimeLimitExceeded):
        OptionsIntelligenceService(repository, market, config).scan(["AAPL"], now=now)
    market.get_option_chain.assert_not_called()


@pytest.mark.parametrize("entry_point", ["scan_all", "scan_selected", "run"])
def test_intraday_anomaly_is_saved_without_notification_or_llm(repository, observation, now, config, entry_point):
    from finance_analysis.options_intelligence.preview_cache import load_preview
    from tests.preview_database import preview_repository

    intraday = now.replace(hour=18)
    market = Mock()
    row = observation.model_copy(
        update={
            "observed_at": intraday,
            "quote_timestamp": intraday,
            "volume_date": intraday.date(),
            "volume": 600,
            "open_interest": 100,
        }
    )
    market.get_option_chain.return_value = OptionChain(symbol="AAPL.US", observed_at=intraday, observations=[row])
    market.get_daily_bars.return_value = SimpleNamespace(data={})
    llm = Mock()
    notifier = Mock()
    preview_repo = preview_repository()
    repository.monitored_symbols = lambda uid=None: ["AAPL.US"]
    service = OptionsIntelligenceService(repository, market, config, llm=llm, preview_repository=preview_repo, notifier=notifier)
    if entry_point == "run":
        service.run("AAPL.US", now=intraday, view="preview")
    else:
        symbols = None if entry_point == "scan_all" else ["AAPL.US"]
        result = service.scan(symbols, now=intraday, view="preview")
        assert result["status_counts"]["success"] == 1
    preview = load_preview(repository=preview_repo, now=intraday, symbol="AAPL.US")
    assert any(event["event_type"] == "VOLUME_OI_ANOMALY" for event in preview["events"])
    assert repository.latest("AAPL.US") is None
    assert llm.mock_calls == []
    assert notifier.mock_calls == []


def test_daily_scan_summarizes_with_llm_and_sends_notification(repository, observation, now, config):
    import json
    from finance_analysis.llm import LLMResult  # pragma: allowlist secret

    market = Mock()
    row = observation.model_copy(update={"volume_date": now.date(), "volume": 600, "open_interest": 100})
    market.get_option_chain.return_value = OptionChain(symbol="AAPL.US", observed_at=now, observations=[row])
    market.get_daily_bars.return_value = SimpleNamespace(data={})
    llm = Mock()
    llm.is_available.return_value = True
    summary_payload = {
        "market_overview": "今日盘后期权活跃度集中在科技龙头。",
        "notable_symbols": ["AAPL.US 出现成交量/OI异常"],
        "protection_vs_direction": "成交活跃不代表净空头。",
        "data_limits": ["Indicative 报价非 NBBO"],
        "risk_notes": ["注意跨期点差风险"],
    }
    llm.complete_text.return_value = LLMResult(text=json.dumps(summary_payload), backend="api", model="test-model")
    notifier = Mock()
    repository.monitored_symbols = lambda uid=None: ["AAPL.US"]
    service = OptionsIntelligenceService(repository, market, config, llm=llm, notifier=notifier)
    result = service.scan(now=now, view="official")
    assert result["status_counts"]["success"] == 1
    llm.complete_text.assert_called_once()
    notifier.send.assert_called_once()
    body = notifier.send.call_args.args[0]
    assert "今日盘后期权活跃度集中在科技龙头" in body
    assert "AAPL.US 出现成交量/OI异常" in body
    assert notifier.send.call_args.kwargs["route_type"] == "report"


def test_explain_request_does_not_hold_options_scan_mutex(monkeypatch, repository, observation, now, config):
    from finance_analysis.tasks import lifecycle  # pragma: allowlist secret
    from finance_analysis.tasks.celery.jobs.options_intelligence import tasks  # pragma: allowlist secret

    service_mock = Mock()
    service_mock.explain.return_value = {"why_it_matters": "ok"}
    monkeypatch.setattr(tasks, "OptionsIntelligenceService", lambda **kwargs: service_mock)
    monkeypatch.setattr(tasks, "get_options_config", lambda: config)
    lock_ctor = Mock()
    monkeypatch.setattr(lifecycle, "PostgreSQLAdvisoryLock", lock_ctor)  # pragma: allowlist secret // pragma: allowlist secret
    monkeypatch.setattr(lifecycle, "get_task_lifecycle_service", lambda: Mock())
    res = tasks.options_request.run(symbol="AAPL.US", explain=True, trade_date=now.date().isoformat(), owner_uid=7)
    assert res == {"why_it_matters": "ok"}
    lock_ctor.assert_not_called()

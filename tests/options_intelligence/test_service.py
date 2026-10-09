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

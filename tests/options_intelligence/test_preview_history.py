"""Storage, date isolation and missing-evidence regressions for official/preview views."""

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import select, func

from finance_analysis.database.models.options_intelligence import (
    OptionContract,
    OptionQuoteSnapshot,
    OptionDailyMetrics,
    OptionAnomalyEvent,
    OptionAnalysis,
)
from finance_analysis.integrations.options.models import OptionChain
from finance_analysis.options_intelligence.engine import analyze
from finance_analysis.options_intelligence.service import OptionsIntelligenceService
from finance_analysis.options_intelligence.preview_cache import load_preview, save_preview, PREVIEW_KEY
from finance_analysis.options_intelligence.views import scan_view


class Cache:
    def __init__(self):
        self.values = {}
        self.ttl = None
        self.queued = None

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, ex):
        if self.queued is not None:
            self.queued.append((key, value, ex))
            return self
        self.values[key], self.ttl = value, ex
        return True

    def pipeline(self, **kwargs):
        self.queued = []
        return self

    def execute(self):
        queued, self.queued = self.queued, None
        return [self.set(*command) for command in queued]


def counts(repo):
    with repo.db.get_session() as session:
        return [
            session.scalar(select(func.count()).select_from(model))
            for model in (
                OptionContract,
                OptionQuoteSnapshot,
                OptionDailyMetrics,
                OptionAnomalyEvent,
                OptionAnalysis,
            )
        ]


def service(repo, row, now, config, cache):
    market = Mock()
    market.get_option_chain.return_value = OptionChain(symbol="AAPL.US", observed_at=now, observations=[row])
    market.get_daily_bars.return_value = SimpleNamespace(data={})
    return OptionsIntelligenceService(repo, market, config, preview_client=cache)


def test_preview_never_writes_any_options_table(repository, observation, now, config):
    intraday = now.replace(hour=18)
    row = observation.model_copy(update={"quote_timestamp": intraday, "observed_at": intraday})
    cache = Cache()
    engine = service(repository, row, intraday, config, cache)
    before = counts(repository)
    result = engine.scan(["AAPL.US"], intraday, view="preview")
    assert result["view"] == "preview" and result["failed_count"] == 0
    assert counts(repository) == before
    preview = load_preview(client=cache, now=intraday)
    assert "contracts" not in preview["items"][0]
    assert load_preview(client=cache, now=intraday, symbol="AAPL.US")["contracts"][0]["symbol"] == row.symbol
    assert preview["trade_date"] == intraday.date().isoformat()
    assert "contracts" not in result["results"][0]  # TaskRecord contains summaries only.
    assert repository.latest("AAPL.US") is None


def test_cache_expires_at_local_midnight_and_rejects_other_dates(now):
    cache = Cache()
    payload = {"trade_date": now.date().isoformat(), "items": []}
    save_preview(payload, client=cache, now=now)
    assert cache.ttl == 6 * 3600  # 22:00 UTC is 18:00 EDT.
    assert load_preview(client=cache, now=now) == payload
    assert load_preview(client=cache, now=now + timedelta(days=1)) is None
    with pytest.raises(ValueError, match="previous session"):
        save_preview(payload, client=cache, now=now + timedelta(days=1))
    cache.values[PREVIEW_KEY] = "broken json"
    assert load_preview(client=cache, now=now) is None


def test_preview_cache_write_failure_fails_task_without_db_writes(repository, observation, now, config):
    intraday = now.replace(hour=18)
    cache = Mock()
    cache.get.return_value = None
    cache.pipeline.side_effect = RuntimeError("redis down")
    with pytest.raises(RuntimeError, match="redis down"):
        service(repository, observation, intraday, config, cache).scan(["AAPL.US"], intraday, view="preview")
    assert counts(repository) == [0] * 5


def test_single_refresh_read_failure_cannot_replace_existing_manifest(now):
    cache = Mock()
    cache.get.side_effect = RuntimeError("redis read failed")
    with pytest.raises(RuntimeError, match="redis read failed"):
        save_preview({"trade_date": now.date().isoformat(), "items": []}, client=cache, now=now, merge=True)
    cache.pipeline.assert_not_called()


def test_failed_preview_preserves_previous_and_single_refresh_merges(repository, observation, now, config):
    intraday = now.replace(hour=18)
    cache = Cache()
    save_preview(
        {"trade_date": now.date().isoformat(), "items": [{"symbol": "MSFT.US", "status": "ready"}]},
        client=cache,
        now=intraday,
    )
    engine = service(repository, observation, intraday, config, cache)
    engine.scan(["AAPL.US"], intraday, view="preview")
    assert {r["symbol"] for r in load_preview(client=cache, now=intraday)["items"]} == {"MSFT.US", "AAPL.US"}
    previous = cache.get(PREVIEW_KEY)
    engine.market.get_option_chain.return_value = OptionChain(symbol="AAPL.US", observed_at=intraday)
    with pytest.raises(ValueError, match="All option scans failed"):
        engine.scan(["AAPL.US"], intraday, view="preview")
    assert cache.get(PREVIEW_KEY) == previous


def test_only_after_close_chains_can_become_official(repository, observation, now, config):
    cache = Cache()
    engine = service(repository, observation, now.replace(hour=18), config, cache)
    with pytest.raises(ValueError, match="Cached intraday"):
        engine.run("AAPL.US", now, view="official")
    with pytest.raises(ValueError, match="30 minutes"):
        engine.run("AAPL.US", now.replace(hour=18), view="official")
    with pytest.raises(ValueError, match="open US session"):
        engine.run("AAPL.US", now, view="preview")
    assert counts(repository) == [0] * 5


def test_official_reads_use_one_date_and_never_fall_back_to_older_symbol(repository, observation, now, config):
    older = now - timedelta(days=1)
    first = observation.model_copy(update={"volume_date": older.date(), "observed_at": older})
    service(repository, first, older, config, Cache()).run("AAPL.US", older, view="official")
    second = observation.model_copy(update={"underlying_symbol": "MSFT.US", "symbol": "MSFT261106P00100000"})
    engine = service(repository, second, now, config, Cache())
    engine.market.get_option_chain.return_value.symbol = "MSFT.US"
    engine.run("MSFT.US", now, view="official")
    rows = repository.scan(["AAPL.US", "MSFT.US"])
    assert rows[0]["status"] == "not_scanned"
    assert rows[1]["trade_date"] == now.date().isoformat()
    assert repository.latest("MSFT.US", older.date()) is None
    assert repository.dates(["AAPL.US", "MSFT.US"]) == [now.date(), older.date()]
    assert repository.scan(["AAPL.US", "MSFT.US"], older.date())[0]["trade_date"] == older.date().isoformat()


def test_repository_rejects_intraday_persistence(repository, observation, now, config):
    chain = OptionChain(symbol="AAPL.US", observed_at=now, observations=[observation])
    metrics = analyze(chain, now.date(), now, [], "14:00", config)
    with pytest.raises(ValueError, match="Only daily"):
        repository.save(chain, metrics, now, "14:00")


def test_warmup_protection_score_uses_observed_put_call_not_fabricated_history(observation, now, config):
    put = observation.model_copy(
        update={
            "data_source": "yfinance",
            "feed_type": "delayed",
            "delta": None,
            "quote_timestamp": None,
            "volume": 200,
        }
    )
    call = put.model_copy(update={"symbol": "AAPL261106C00100000", "option_type": "call", "volume": 400})
    result = analyze(
        OptionChain(symbol="AAPL.US", observed_at=now, observations=[put, call]), now.date(), now, [], "daily", config
    )
    score = result["scores"]["bearish_demand"]
    assert score["value"] == 25 and score["method"] == "initial_protection_demand_rules"
    assert score["confidence"] == "low" and result["iv_percentile"] is None
    assert result["scores"]["liquidity_risk"]["value"] is not None
    assert all(c["risk"]["value"] is None for c in result["contracts"])
    assert not any(e["event_type"] in {"WIDE_BID_ASK_SPREAD", "LIQUIDITY_DRY_UP"} for e in result["events"])
    # Research scores are preserved after close and when reading past dates.
    assert scan_view(result)["scores"] == result["scores"]
    assert scan_view(scan_view(result)) == scan_view(result)
    stale = [r.model_copy(update={"volume_date": now.date() - timedelta(days=1)}) for r in (put, call)]
    assert (
        analyze(
            OptionChain(symbol="AAPL.US", observed_at=now, observations=stale), now.date(), now, [], "daily", config
        )["scores"]["bearish_demand"]["value"]
        is None
    )


def test_old_primary_volume_does_not_hide_current_fallback_put_call(observation, now, config):
    put = observation.model_copy(update={"volume": 200, "feed_type": "indicative"})
    call = put.model_copy(update={"symbol": "AAPL261106C00100000", "option_type": "call", "volume": 400})
    old = [
        r.model_copy(
            update={
                "data_source": "yfinance",
                "feed_type": "delayed",
                "quote_timestamp": None,
                "volume_date": now.date() - timedelta(days=1),
            }
        )
        for r in (put, call)
    ]
    result = analyze(
        OptionChain(symbol="AAPL.US", observed_at=now, observations=old + [put, call]),
        now.date(),
        now,
        [],
        "daily",
        config,
    )
    assert result["put_call_volume_ratio"] == 0.5
    assert result["volume_source"] == "alpaca"
    assert result["scores"]["bearish_demand"]["value"] is not None


def test_preview_uses_prior_daily_iv_but_never_daily_volume_percentiles(observation, now, config):
    call = observation.model_copy(update={"symbol": "AAPL261106C00100000", "option_type": "call", "delta": 0.25})
    chain = OptionChain(symbol="AAPL.US", observed_at=now, observations=[observation, call])
    history = [
        {
            "trade_date": now.date() - timedelta(days=i),
            "mode": "daily",
            "rows": [],
            "metrics": {"iv_30d": 0.2, "iv_source": ["alpaca", "opra"]},
        }
        for i in range(1, 21)
    ]
    result = analyze(chain, now.date(), now, history, "14:00", config)
    assert result["iv_percentile"] == 100
    assert result["history_days"] == 20 and result["volume_history_days"] == 0
    assert result["volatility_comparison"] == "prior_daily_closes"
    assert all(r["volume_percentile"] is None for r in result["contracts"])
    assert result["scores"]["bearish_demand"]["confidence"] == "low"

from datetime import timedelta
from finance_analysis.integrations.options.models import OptionChain
from finance_analysis.database.models.options_intelligence import OptionContract
from finance_analysis.options_intelligence.engine import analyze


def save(repo, observation, now, config, **update):
    chain = OptionChain(symbol="AAPL.US", observed_at=now, observations=[observation])
    metrics = analyze(chain, now.date(), now, [], "daily", config)
    metrics.update(update)
    return repo.save(chain, metrics, now, "daily")


def test_snapshot_and_event_dedup_and_immutable_initial(repository, observation, now, config):
    first = save(repository, observation, now, config)
    assert save(repository, observation, now, config) == first
    original = repository.events("AAPL.US")
    assert len(original) == 1 and original[0]["event_type"] == "VOLUME_OI_ANOMALY"
    later = now + timedelta(minutes=30)
    save(repository, observation.model_copy(update={"volume": 700, "observed_at": later}), later, config)
    events = repository.events("AAPL.US")
    assert len(events) == 1
    assert events[0]["initial_evidence"]["value"] == 5
    assert events[0]["latest_evidence"]["value"] == 7
    assert len(events[0]["changes"]) == 1
    assert len(repository.daily("AAPL.US")) == 1
    history = repository.history("AAPL.US", now.date() + timedelta(days=1), 120, "daily")
    assert len(history) == 1  # do not count multiple scans as multiple independent daily samples


def test_next_day_oi_updates_validation_only(repository, observation, now, config):
    save(repository, observation, now, config)
    first = repository.events("AAPL.US")[0]
    later = now + timedelta(days=1)
    change = {
        "change": 200,
        "previous": 100,
        "oi_date": now.date().isoformat(),
        "previous_oi_date": (now.date() - timedelta(days=1)).isoformat(),
        "known_at": later.isoformat(),
        "source": "alpaca",
    }
    row = observation.model_copy(update={"open_interest": 300, "observed_at": later})
    chain = OptionChain(symbol="AAPL.US", observed_at=later, observations=[row])
    metrics = analyze(
        chain,
        later.date(),
        later,
        [],
        "daily",
        config,
        oi_changes={(row.symbol, row.data_source, row.feed_type): change},
    )
    repository.save(chain, metrics, later, "daily")
    old = next(e for e in repository.events("AAPL.US") if e["trade_date"] == now.date())
    assert old["initial_evidence"] == first["initial_evidence"]
    assert old["validation"]["oi_confirmation"]["known_at"] == later.isoformat()
    assert old["validation"]["oi_confirmation"]["oi_date"] == now.date().isoformat()
    assert repository.daily("AAPL.US")[0]["events"][0]["event_type"] == "VOLUME_OI_ANOMALY"


def test_oi_flat_is_recorded_without_confirmed_build_up(repository, observation, now, config):
    save(repository, observation, now, config)
    later = now + timedelta(days=1)
    change = {
        "change": 0,
        "previous": 100,
        "oi_date": now.date().isoformat(),
        "previous_oi_date": (now.date() - timedelta(days=1)).isoformat(),
        "known_at": later.isoformat(),
        "source": "alpaca",
    }
    chain = OptionChain(symbol="AAPL.US", observed_at=later, observations=[observation])
    metrics = analyze(
        chain, later.date(), later, [], "daily", config, oi_changes={(observation.symbol, "alpaca", "opra"): change}
    )
    repository.save(chain, metrics, later, "daily")
    old = next(e for e in repository.events("AAPL.US") if e["trade_date"] == now.date())
    assert old["validation"]["status"] == "no_net_oi_increase"
    assert not any(e["event_type"] == "OI_BUILDUP_CONFIRMED" for e in repository.events("AAPL.US"))


def test_event_reference_changes_are_saved_without_new_event(repository, observation, now, config):
    save(repository, observation, now, config)
    original = repository.events("AAPL.US")[0]
    later = now + timedelta(minutes=30)
    chain = OptionChain(symbol="AAPL.US", observed_at=later, observations=[observation])
    metrics = analyze(chain, now.date(), later, [], "daily", config)
    metrics["events"][0]["reference"] = {"threshold": 4}
    metrics["events"][0]["severity"] = 90
    repository.save(chain, metrics, later, "daily")
    events = repository.events("AAPL.US")
    assert len(events) == 1
    event = events[0]
    assert event["initial_evidence"] == original["initial_evidence"]
    assert event["latest_evidence"]["reference"] == {"threshold": 4}
    assert event["latest_evidence"]["severity"] == 90
    assert len(event["changes"]) == 1
    # A scan with unchanged material evidence updates freshness without adding redundant changes.
    repository.save(chain, metrics, later + timedelta(minutes=30), "daily")
    assert len(repository.events("AAPL.US")[0]["changes"]) == 1


def test_confirmed_multiplier_fills_missing_master_without_overwriting_snapshot(repository, observation, now, config):
    first = observation.model_copy(update={"multiplier": None})
    save(repository, first, now, config)
    save(repository, observation, now + timedelta(minutes=30), config)
    with repository.db.get_session() as session:
        assert session.get(OptionContract, observation.symbol).multiplier == 100
    prior = repository.history("AAPL.US", now.date() + timedelta(days=1), 7, "daily")[0]
    assert prior["rows"][0].multiplier is None

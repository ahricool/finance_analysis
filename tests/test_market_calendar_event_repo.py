"""Real SQL tests for logical calendar identity and source provenance."""

import json
from contextlib import contextmanager
from datetime import date

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from finance_analysis.database.models import FinanceEvent
from finance_analysis.database.repositories.market_calendar_event import (
    MarketCalendarEventRepo,
    notification_fingerprint,
)
from finance_analysis.market_calendar.events import macro_type, merge_events, with_source

AS_OF = date(2026, 6, 18)


class CalendarDB:
    def __init__(self):
        self.engine = create_engine("sqlite://")
        FinanceEvent.__table__.create(self.engine)

    @contextmanager
    def get_session(self):
        with Session(self.engine, expire_on_commit=False) as session:
            yield session

    def _run_write_transaction(self, name, callback):
        with self.get_session() as session, session.begin():
            return callback(session)


@pytest.fixture
def repo():
    return MarketCalendarEventRepo(db=CalendarDB())


def event(provider="yfinance", **overrides):
    values = dict(
        provider=provider,
        calendar_type="earnings",
        market="US",
        symbol="NVDA.US",
        event_date="2026-06-20",
        event_type="earnings_release",
        title="NVIDIA 财报",
        content="Q2 earnings",
        market_session="unknown",
    )
    values.update(overrides)
    return with_source(values)


def write(repo, data):
    return repo.upsert_event(data, as_of=AS_OF)


def test_two_providers_one_event_and_yahoo_conflict_wins(repo):
    a = event(eps_estimate=0.0, event_date="2026-06-20")
    b = event("longbridge", provider_event_id="lb-1", event_date="2026-06-21", currency="USD", market_session="amc")
    merged = merge_events([b, a], as_of=AS_OF)
    assert len(merged) == 1
    result = write(repo, merged[0])
    assert result.event.provider == "yfinance"
    assert result.event.provider_event_id is None
    assert result.event.eps_estimate == 0.0
    assert result.event.market_session == "amc"
    audit = json.loads(result.event.raw_payload_json)
    assert set(audit) == {"yfinance", "longbridge", "conflicts"}
    assert audit["conflicts"]["event_date"]["yfinance"] == "2026-06-20"
    assert audit["longbridge"]["normalized"]["provider_event_id"] == "lb-1"


def test_date_change_updates_original_id_key_and_first_seen(repo):
    old = write(repo, event()).event
    new = write(repo, event(event_date="2026-06-19", market_session="bmo"))
    assert not new.created
    assert new.event.id == old.id
    assert new.event.event_key == old.event_key
    assert new.event.first_seen_at == old.first_seen_at
    assert set(new.changed_fields) >= {"event_date", "market_session"}
    assert len(repo.list_events_by_date_range(AS_OF, date(2026, 7, 1))) == 1


def test_longbridge_only_is_honest_then_yahoo_promotes_same_row(repo):
    old = write(repo, event("longbridge", provider_event_id="a", market_session="amc")).event
    assert old.provider == "longbridge"
    new = write(repo, event(event_date="2026-06-19", eps_estimate=1.2)).event
    assert new.provider == "yfinance" and new.id == old.id and new.event_key == old.event_key
    assert new.market_session == "amc"
    failed_primary_run = write(repo, event("longbridge", event_date="2026-06-21", currency="USD")).event
    assert failed_primary_run.provider == "yfinance" and failed_primary_run.eps_estimate == 1.2
    assert failed_primary_run.event_date == date(2026, 6, 19)


def test_explicit_fiscal_period_survives_large_date_change(repo):
    old = write(repo, event(reporting_period="2026-Q2")).event
    new = write(repo, event(reporting_period="2026-Q2", event_date="2026-08-15")).event
    assert old.id == new.id
    next_period = write(repo, event(reporting_period="2026-Q3", event_date="2026-08-16"))
    assert next_period.created


def test_next_quarter_and_old_events_are_not_conflated(repo):
    write(repo, event(event_date="2026-03-20"))
    assert write(repo, event()).created
    assert write(repo, event(event_date="2026-09-20")).created


def test_source_id_matches_release_correction_after_grace(repo):
    old = write(repo, event("longbridge", provider_event_id="period-1", event_date="2026-06-01")).event
    updated = write(repo, event("longbridge", provider_event_id="period-1", event_date="2026-06-02"))
    assert updated.event.id == old.id


def test_ambiguous_candidate_is_reported_not_guessed(repo):
    write(repo, event(reporting_period="2026-Q1", event_date="2026-06-19"))
    write(repo, event(reporting_period="2026-Q2", event_date="2026-06-21"))
    with pytest.raises(ValueError, match="ambiguous"):
        write(repo, event())


def test_repeated_observation_is_idempotent_and_retains_assessment(repo):
    first = write(repo, event()).event
    with repo.db.get_session() as session, session.begin():
        obj = session.get(FinanceEvent, first.id)
        obj.importance_score = 9
    repeated = write(repo, event())
    assert not repeated.created and not repeated.updated
    assert repeated.event.importance_score == 9


def test_macro_aliases_merge_but_core_and_frequencies_remain_separate(repo):
    a = event(calendar_type="macro", symbol=None, event_type=macro_type("CPI YY"), title="CPI YY")
    b = event("longbridge", calendar_type="macro", symbol=None, event_type=macro_type("美国CPI年率"))
    assert len(merge_events([a, b], as_of=AS_OF)) == 1
    first = write(repo, a).event
    assert write(repo, b).event.id == first.id
    for name in ("Core CPI YY", "CPI MM"):
        assert write(repo, event(calendar_type="macro", symbol=None, event_type=macro_type(name))).created
    assert write(
        repo, event(calendar_type="macro", symbol=None, event_type=macro_type("CPI YY"), event_date="2026-07-20")
    ).created


def test_macro_same_period_date_adjustment_updates(repo):
    first = write(
        repo, event(calendar_type="macro", symbol=None, event_type="cpi_yoy", reporting_period="2026-05")
    ).event
    moved = write(
        repo,
        event(
            calendar_type="macro",
            symbol=None,
            event_type="cpi_yoy",
            reporting_period="2026-05",
            event_date="2026-06-21",
        ),
    )
    assert moved.event.id == first.id


def test_notification_fingerprint_ignores_enrichment_but_detects_session_and_date():
    data = event()
    original = notification_fingerprint(data)
    assert notification_fingerprint(data | dict(provider="longbridge", currency="USD", eps_estimate=3)) == original
    assert notification_fingerprint(data | dict(market_session="amc")) != original
    assert notification_fingerprint(data | dict(event_date="2026-06-19")) != original


@pytest.mark.parametrize("kind", ["ipo", "dividend", "split"])
def test_removed_calendar_types_rejected(repo, kind):
    with pytest.raises(ValueError, match="unsupported"):
        write(repo, event(calendar_type=kind))


def test_reject_non_us_macro(repo):
    with pytest.raises(ValueError, match="US macro"):
        write(repo, event(calendar_type="macro", market="CN", symbol=None))


def test_explicit_period_wins_over_nearby_ambiguous_candidate(repo):
    known = write(repo, event(reporting_period="2026-Q2", event_date="2026-06-20")).event
    write(repo, event(reporting_period="2026-Q1", event_date="2026-06-19"))
    changed = write(repo, event(reporting_period="2026-Q2", event_date="2026-06-21"))
    assert changed.event.id == known.id


def test_macro_repeated_same_day_times_are_not_collapsed(repo):
    first = write(
        repo,
        event(calendar_type="macro", symbol=None, event_type="fed_speech", event_datetime="2026-06-20T10:00:00+00:00"),
    )
    second = write(
        repo,
        event(calendar_type="macro", symbol=None, event_type="fed_speech", event_datetime="2026-06-20T18:00:00+00:00"),
    )
    assert first.created and second.created


def test_secondary_timestamp_on_conflicting_date_is_not_copied_to_primary_date():
    result = merge_events(
        [event(), event("longbridge", event_date="2026-06-21", event_datetime="2026-06-21T20:00:00Z")], as_of=AS_OF
    )[0]
    assert result["event_date"] == "2026-06-20" and result["event_datetime"] is None


def test_postgresql_concurrent_sources_share_logical_identity():
    import os
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from uuid import uuid4

    from sqlalchemy import text

    url = os.getenv("CALENDAR_TEST_DATABASE_URL")
    if not url:
        pytest.skip("requires explicitly configured isolated PostgreSQL test database")
    engine = create_engine(url)
    schema = "calendar_concurrency_" + uuid4().hex
    with engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    scoped = engine.execution_options(schema_translate_map={None: schema})
    try:
        FinanceEvent.__table__.create(scoped)
        db = CalendarDB.__new__(CalendarDB)
        db.engine = scoped
        repo = MarketCalendarEventRepo(db=db)
        barrier = Barrier(2)

        def insert(provider):
            barrier.wait(timeout=10)
            return write(repo, event(provider)).event.id

        with ThreadPoolExecutor(max_workers=2) as pool:
            ids = list(pool.map(insert, ["yfinance", "longbridge"]))
        assert ids[0] == ids[1]
        rows = repo.list_events_by_date(date(2026, 6, 20))
        assert len(rows) == 1 and rows[0].provider == "yfinance"
        assert {"yfinance", "longbridge"} <= set(json.loads(rows[0].raw_payload_json))
    finally:
        with engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        engine.dispose()


@pytest.mark.parametrize(
    "yahoo,longbridge",
    [
        ("Fed Funds Target Rate", "美国美联储利率决议"),
        ("Fed Funds Target Rate Upper Bound", "美国美联储利率决定上限"),
        ("Non-Farm Payrolls", "美国季调后非农就业人口"),
        ("Core PCE MM", "美国核心个人消费支出月率"),
    ],
)
def test_macro_known_cross_language_release_aliases(yahoo, longbridge):
    assert macro_type(yahoo) == macro_type(longbridge)

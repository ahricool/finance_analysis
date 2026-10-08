from contextlib import contextmanager
from datetime import datetime, date, timezone
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from finance_analysis.database.models.options_intelligence import (
    OptionContract,
    OptionQuoteSnapshot,
    OptionDailyMetrics,
    OptionAnomalyEvent,
    OptionAnalysis,
)
from finance_analysis.database.repositories.options_intelligence import OptionsRepository
from finance_analysis.integrations.options.models import OptionObservation
from finance_analysis.options_intelligence.config import OptionsConfig


@pytest.fixture
def now():
    return datetime(2026, 10, 7, 18, 0, tzinfo=timezone.utc)


@pytest.fixture
def config():
    return OptionsConfig()


@pytest.fixture
def observation(now):
    return OptionObservation(
        symbol="AAPL261106P00100000",
        underlying_symbol="AAPL.US",
        option_type="put",
        expiration=date(2026, 11, 6),
        strike=100,
        multiplier=100,
        bid=2,
        ask=2.2,
        bid_size=10,
        ask_size=10,
        volume=500,
        volume_date=now.date(),
        open_interest=100,
        iv=0.3,
        delta=-0.25,
        underlying_price=100,
        quote_timestamp=now,
        iv_timestamp=now,
        observed_at=now,
        data_source="alpaca",
        feed_type="opra",
    )


@pytest.fixture
def repository():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    for model in (OptionContract, OptionQuoteSnapshot, OptionDailyMetrics, OptionAnomalyEvent, OptionAnalysis):
        model.__table__.create(engine)

    class DB:
        @contextmanager
        def get_session(self):
            with Session(engine) as session:
                yield session

        @contextmanager
        def session_scope(self):
            with Session(engine) as session, session.begin():
                yield session

    yield OptionsRepository(DB())
    engine.dispose()

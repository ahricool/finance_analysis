from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from finance_analysis.database.models.stock_strategies import (
    StockStrategyDay,
    StockStrategyLaunch,
    StockStrategyRun,
    StockStrategyState,
)
from finance_analysis.database.repositories.stock_strategies import StockStrategyRepository


@pytest.fixture
def repository():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    for model in (StockStrategyLaunch, StockStrategyState, StockStrategyDay, StockStrategyRun):
        model.__table__.create(engine)

    class DB:
        def get_session(self):
            return Session(engine)

        @contextmanager
        def session_scope(self):
            with Session(engine) as session, session.begin():
                yield session

    yield StockStrategyRepository(DB())
    engine.dispose()

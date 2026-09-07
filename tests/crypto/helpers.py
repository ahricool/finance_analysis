from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from finance_analysis.crypto.models import Kline
from finance_analysis.database.models.crypto import CryptoKline, CryptoStrategySnapshot, CryptoStrategyState

START = datetime(2026, 8, 1, tzinfo=timezone.utc)


def candle(index=0, **changes):
    start = START + timedelta(minutes=index)
    price = Decimal(100) + Decimal(index) / 100
    return replace(
        Kline(
            start,
            start + timedelta(minutes=1),
            price,
            price + 1,
            price - 1,
            price,
            Decimal("1.123456789012"),
            Decimal(200),
            3,
            Decimal("0.5"),
            Decimal(100),
        ),
        **changes,
    )


class Database:
    def __init__(self, engine=None):
        self.engine = engine or create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        for model in (CryptoKline, CryptoStrategyState, CryptoStrategySnapshot):
            model.__table__.create(self.engine)

    @contextmanager
    def get_session(self):
        with Session(self.engine) as session:
            yield session

    @contextmanager
    def session_scope(self):
        with Session(self.engine) as session, session.begin():
            yield session

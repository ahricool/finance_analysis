from contextlib import contextmanager
from datetime import date

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from finance_analysis.database.models.stock import Instrument, StockDaily
from finance_analysis.database.repositories.quant import QuantRepository
from finance_analysis.quant.signal_returns import signal_returns


class Database:
    def __init__(self):
        self.engine = create_engine("sqlite:///:memory:")
        Instrument.__table__.create(self.engine)
        StockDaily.__table__.create(self.engine)

    @contextmanager
    def get_session(self):
        with Session(self.engine) as session:
            yield session


def test_batch_returns_windows_signal_fallback_and_query_count():
    db = Database()
    dates = [date(2026, 9, day) for day in (10, 11, 14, 15, 16, 17, 18, 21)]
    with db.get_session() as session:
        for i in range(1, 51):
            session.add(Instrument(id=i, market="US", code=f"S{i}.US", name=f"S{i}"))
            for j, day in enumerate(dates):
                session.add(
                    StockDaily(
                        id=i * 100 + j,
                        instrument_id=i,
                        date=day,
                        open=100,
                        high=120,
                        low=90,
                        close=100 + j,
                        volume=10,
                        data_source="test",
                    )
                )
        session.commit()
    queries = []
    event.listen(db.engine, "before_cursor_execute", lambda *args: queries.append(args[2]))
    repo = QuantRepository(db)
    result = signal_returns(repo, {f"S{i}.US" for i in range(1, 51)} | {"MISSING.US"}, date(2026, 9, 12))
    assert len(queries) == 1
    assert result["S1.US"] == {
        "return_3d": pytest.approx(107 / 105 - 1),
        "return_5d": pytest.approx(107 / 103 - 1),
        "return_since": pytest.approx(107 / 102 - 1),
        "return_as_of": dates[-1],
    }
    assert all(value is None for value in result["MISSING.US"].values())
    # An old signal's base must survive the five-bar tail truncation.
    assert signal_returns(repo, {"S1.US"}, dates[0])["S1.US"]["return_since"] == pytest.approx(0.07)
    assert signal_returns(repo, {"S1.US"}, date(2026, 9, 22))["S1.US"]["return_since"] is None
    assert signal_returns(repo, {"S1.US"}, None)["S1.US"]["return_since"] is None
    assert signal_returns(repo, set(), None) == {}


@pytest.mark.parametrize(
    "closes",
    [
        [],
        [100],
        [100, 101],
        [100, 101, 102],
        [100, 101, 102, 103],
        [100, 101, 102, 103, 104],
        [0, 100, 110],
        [100, 101, 0],
    ],
)
def test_short_histories_and_invalid_prices(closes):
    db = Database()
    with db.get_session() as session:
        session.add(Instrument(id=1, market="US", code="TEST.US", name="Test"))
        for i, close in enumerate(closes):
            session.add(
                StockDaily(
                    id=i + 1,
                    instrument_id=1,
                    date=date(2026, 9, i + 1),
                    open=100,
                    high=120,
                    low=90,
                    close=close,
                    volume=0,
                    data_source="test",
                )
            )
        session.commit()
    result = signal_returns(QuantRepository(db), {"TEST.US"}, date(2026, 9, 1))["TEST.US"]
    for n in (3, 5):
        expected = closes[-1] / closes[-n] - 1 if len(closes) >= n and closes[-n] > 0 and closes[-1] > 0 else None
        assert result[f"return_{n}d"] == (pytest.approx(expected) if expected is not None else None)
    valid = [value for value in closes if value > 0]
    expected_since = closes[-1] / valid[0] - 1 if valid and closes[-1] > 0 else None
    assert result["return_since"] == (pytest.approx(expected_since) if expected_since is not None else None)

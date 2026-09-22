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


DATES = [date(2026, 9, day) for day in (10, 11, 14, 15, 16, 17, 18, 21)]
EMPTY = dict(return_3d=None, return_5d=None, return_since=None, return_as_of=None)


def seed(db, closes, count=1):
    with db.get_session() as session:
        for i in range(1, count + 1):
            session.add(Instrument(id=i, market="US", code=f"S{i}.US", name=f"S{i}"))
            for j, close in enumerate(closes):
                session.add(
                    StockDaily(
                        id=i * 100 + j,
                        instrument_id=i,
                        date=DATES[j],
                        open=100,
                        high=120,
                        low=90,
                        close=close,
                        volume=10,
                        data_source="test",
                    )
                )
        session.commit()


def test_batch_forward_returns_weekend_and_query_count():
    db = Database()
    seed(db, [100, 101, 102, 103, 104, 105, 106, 107], count=50)
    queries = []
    event.listen(db.engine, "before_cursor_execute", lambda *args: queries.append(args[2]))
    result = signal_returns(QuantRepository(db), {f"S{i}.US" for i in range(1, 51)} | {"MISSING.US"}, DATES[0])
    assert len(queries) == 1
    assert result["S1.US"] == {
        "return_3d": pytest.approx(0.03),  # Sep 15, after the weekend
        "return_5d": pytest.approx(0.05),  # Sep 17, not latest close
        "return_since": pytest.approx(0.07),
        "return_as_of": DATES[-1],
    }
    assert result["MISSING.US"] == EMPTY


@pytest.mark.parametrize("future_count", range(6))
def test_future_data_must_exist_and_today_never_uses_past_returns(future_count):
    db = Database()
    # There is older data, but only future_count bars after the selected date.
    seed(db, [80, 90, 100, 110, 120, 130, 140, 150][: 3 + future_count])
    result = signal_returns(QuantRepository(db), {"S1.US"}, DATES[2])["S1.US"]
    assert result["return_3d"] == (pytest.approx(0.3) if future_count >= 3 else None)
    assert result["return_5d"] == (pytest.approx(0.5) if future_count >= 5 else None)
    assert result["return_since"] == (pytest.approx(future_count / 10) if future_count else None)
    assert result["return_as_of"] == (DATES[2 + future_count] if future_count else None)


@pytest.mark.parametrize("quant_date", [date(2026, 9, 9), date(2026, 9, 12), date(2026, 9, 22), None])
def test_missing_exact_baseline_never_shifts_to_next_bar(quant_date):
    db = Database()
    seed(db, [100] * 8)
    assert signal_returns(QuantRepository(db), {"S1.US"}, quant_date)["S1.US"] == EMPTY


@pytest.mark.parametrize(
    "closes,expected_3d,expected_5d,expected_since,as_of",
    [
        ([0, 101, 102, 103, 104, 105], None, None, None, None),
        ([100, 101, 102, 0, 104, 105], None, 0.05, 0.05, DATES[5]),
        ([100, 101, 102, 103, 104, 0], 0.03, None, 0.04, DATES[4]),
        ([100, 0, 0, 0], None, None, None, None),
        ([100, 100, 100, 100, 100, 100], 0, 0, 0, DATES[5]),
        ([100, 99, 98, 97, 96, 95], -0.03, -0.05, -0.05, DATES[5]),
    ],
)
def test_invalid_endpoints_latest_valid_and_true_zero(closes, expected_3d, expected_5d, expected_since, as_of):
    db = Database()
    seed(db, closes)
    result = signal_returns(QuantRepository(db), {"S1.US"}, DATES[0])["S1.US"]
    for key, expected in [("return_3d", expected_3d), ("return_5d", expected_5d), ("return_since", expected_since)]:
        assert result[key] == (pytest.approx(expected) if expected is not None else None)
    assert result["return_as_of"] == as_of


def test_empty_list_does_not_query():
    db = Database()
    queries = []
    event.listen(db.engine, "before_cursor_execute", lambda *args: queries.append(args[2]))
    assert signal_returns(QuantRepository(db), set(), DATES[0]) == {}
    assert not queries

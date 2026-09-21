"""Repository query keeps notification dedupe scoped to local date and notified signals."""
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from finance_analysis.database.models.trade_engine import TradeSignalRow
from finance_analysis.database.repositories.trade_engine import TradeEngineRepository


@pytest.mark.parametrize("market,zone,day,hours", [
    ("US", "America/New_York", date(2026, 3, 8), 23),
    ("US", "America/New_York", date(2026, 11, 1), 25),
    ("CN", "Asia/Shanghai", date(2026, 9, 16), 24),
])
def test_notified_actions_local_day_range_and_isolation(market, zone, day, hours):
    engine = create_engine("sqlite://")
    TradeSignalRow.__table__.create(engine)
    tz = ZoneInfo(zone)
    start = datetime.combine(day, time.min, tzinfo=tz).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz).astimezone(timezone.utc)
    assert (end - start).total_seconds() == hours * 3600
    rows = [
        (1, market, "KEEP", "REDUCE", start, 1),
        (1, market, "KEEP", "EXIT", end - timedelta(seconds=1), 2),
        (1, market, "BEFORE", "REDUCE", start - timedelta(seconds=1), 3),
        (1, market, "AFTER", "REDUCE", end, 4),
        (1, market, "UNNOTIFIED", "REDUCE", start, None),
        (2, market, "OTHER_USER", "REDUCE", start, 5),
        (1, "CN" if market == "US" else "US", "OTHER_MARKET", "REDUCE", start, 6),
    ]
    with Session(engine) as session:
        for index, (uid, row_market, symbol, action, stamp, notification_id) in enumerate(rows, 1):
            session.add(TradeSignalRow(
                id=index, uid=uid, market=row_market, symbol=symbol, action=action,
                strategy_key="market_llm", strategy_version="1", signal_key=str(index),
                evaluated_at=stamp, notification_id=notification_id,
            ))
        session.commit()
        repository = TradeEngineRepository(db=object())
        assert repository.notified_actions_for_date(session, uid=1, market=market, local_date=day) == {
            ("KEEP", "REDUCE"), ("KEEP", "EXIT"),
        }
    engine.dispose()

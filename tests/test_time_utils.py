# -*- coding: utf-8 -*-
"""Timezone adaptation regression tests."""

from datetime import date, datetime, timezone

from sqlalchemy import DateTime

from finance_analysis.database import Base, DatabaseManager
from finance_analysis.core.time import day_bounds_utc, utc_isoformat


def test_utc_isoformat_uses_z_with_milliseconds() -> None:
    value = datetime(2026, 6, 10, 1, 30, 0, 123456, tzinfo=timezone.utc)

    assert utc_isoformat(value) == "2026-06-10T01:30:00.123Z"


def test_day_bounds_utc_honors_new_york_dst() -> None:
    summer_start, summer_end = day_bounds_utc(date(2026, 6, 10), "America/New_York")
    winter_start, winter_end = day_bounds_utc(date(2026, 1, 10), "America/New_York")

    assert summer_start.isoformat() == "2026-06-10T04:00:00+00:00"
    assert summer_end.isoformat() == "2026-06-11T04:00:00+00:00"
    assert winter_start.isoformat() == "2026-01-10T05:00:00+00:00"
    assert winter_end.isoformat() == "2026-01-11T05:00:00+00:00"


def test_all_orm_datetime_columns_are_timezone_aware() -> None:
    datetime_columns = [
        column
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, DateTime)
    ]

    assert datetime_columns
    assert all(column.type.timezone is True for column in datetime_columns)


def test_postgres_connection_hook_sets_utc_timezone() -> None:
    statements: list[str] = []

    class Cursor:
        def execute(self, statement: str) -> None:
            statements.append(statement)

        def close(self) -> None:
            statements.append("closed")

    class Connection:
        def cursor(self) -> Cursor:
            return Cursor()

    DatabaseManager._set_utc_timezone(Connection(), object())

    assert statements == ["SET TIME ZONE 'UTC'", "closed"]

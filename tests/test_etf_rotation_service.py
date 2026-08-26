from __future__ import annotations

from datetime import date, timedelta
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from finance_analysis.database.repositories.etf_rotation import ETFRotationRepository
from finance_analysis.etf_rotation.readiness import ETFRotationReadinessError
from finance_analysis.etf_rotation.service import ETFRotationService
from finance_analysis.etf_rotation.universe import enabled_etfs

TRADE_DATE = date(2026, 8, 25)


class FakeRepository:
    def __init__(self, *, ready_count: int = 40, history_bars: int = 61):
        self.codes = [member.code for member in enabled_etfs()]
        self.ready_count = ready_count
        self.history_bars = history_bars
        self.saved: dict[tuple[str, str], dict] = {}

    def latest_daily_dates(self, _codes):
        return {
            code: TRADE_DATE if index < self.ready_count else TRADE_DATE - timedelta(days=1)
            for index, code in enumerate(self.codes)
        }

    def daily_codes_on_date(self, _codes, _trade_date):
        return set(self.codes[: self.ready_count])

    def load_daily_history(self, codes, trade_date):
        rows = []
        selected = sorted(codes)
        start = trade_date - timedelta(days=self.history_bars - 1)
        for code_index, code in enumerate(selected):
            for index in range(self.history_bars):
                rows.append(
                    {
                        "symbol_id": code_index + 1,
                        "code": code,
                        "trade_date": start + timedelta(days=index),
                        "close": 100 + index * (1 + code_index / 100),
                        "volume": 1000 + index,
                        "amount": 100_000 + index,
                    }
                )
        return rows

    def historical_rank_5d(self, _trade_date, _codes):
        return {}

    def upsert_snapshots(self, snapshots):
        for snapshot in snapshots:
            self.saved[(snapshot["trade_date"].isoformat(), snapshot["code"])] = dict(snapshot)
        return len(snapshots)


def test_service_generates_complete_snapshot_and_same_date_rerun_is_idempotent() -> None:
    repository = FakeRepository()
    service = ETFRotationService(repository=repository)
    first = service.run(TRADE_DATE)
    second = service.run(TRADE_DATE)
    assert first["snapshot_count"] == second["snapshot_count"] == 40
    assert len(repository.saved) == 40
    assert first["candidate_count"] == 5
    assert all("score_components" in snapshot for snapshot in repository.saved.values())


def test_service_refuses_insufficient_daily_coverage_without_writes() -> None:
    repository = FakeRepository(ready_count=35)
    with pytest.raises(ETFRotationReadinessError, match="daily data"):
        ETFRotationService(repository=repository).run(TRADE_DATE)
    assert repository.saved == {}


def test_service_refuses_insufficient_rankable_coverage_without_writes() -> None:
    repository = FakeRepository(history_bars=60)
    with pytest.raises(ETFRotationReadinessError, match="rankable"):
        ETFRotationService(repository=repository).run(TRADE_DATE)
    assert repository.saved == {}


def test_repository_uses_postgresql_conflict_update_for_idempotent_reruns() -> None:
    session = MagicMock()
    session.execute.side_effect = [
        SimpleNamespace(all=lambda: [(member.code, index + 1) for index, member in enumerate(enabled_etfs())]),
        MagicMock(),
        MagicMock(),
    ]

    class FakeDatabase:
        @contextmanager
        def session_scope(self):
            yield session

    snapshots = list(FakeRepository().saved.values())
    if not snapshots:
        fake = FakeRepository()
        ETFRotationService(repository=fake).run(TRADE_DATE)
        snapshots = list(fake.saved.values())
    assert ETFRotationRepository(FakeDatabase()).upsert_snapshots(snapshots) == 40
    upsert_sql = str(session.execute.call_args_list[1].args[0].compile(dialect=postgresql.dialect()))
    cleanup_sql = str(session.execute.call_args_list[2].args[0].compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT ON CONSTRAINT uix_etf_momentum_snapshot_date_symbol DO UPDATE" in upsert_sql
    assert "DELETE FROM etf_momentum_snapshot" in cleanup_sql

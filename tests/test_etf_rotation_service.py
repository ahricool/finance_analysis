from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from sqlalchemy.dialects import postgresql

from finance_analysis.database.repositories.etf_rotation import ETFRotationRepository
from finance_analysis.etf_rotation.readiness import ETFRotationReadinessError
from finance_analysis.etf_rotation.service import ETFRotationService
from finance_analysis.etf_rotation.universe import enabled_etfs

TRADE_DATE = date(2026, 8, 25)


class FakeRepository:
    def __init__(self, *, market: str = "CN", ready_count: int | None = None, history_bars: int = 61):
        self.market = market
        self.codes = [member.code for member in enabled_etfs(market)]
        ready_count = len(self.codes) if ready_count is None else ready_count
        self.ready_count = ready_count
        self.history_bars = history_bars
        self.saved: dict[tuple[str, str], dict] = {}
        self.coverage_codes: set[str] = set()

    def latest_daily_dates(self, _codes):
        self.coverage_codes = set(_codes)
        return {
            code: TRADE_DATE if index < self.ready_count else TRADE_DATE - timedelta(days=1)
            for index, code in enumerate(self.codes)
        }

    def daily_codes_on_date(self, _codes, _trade_date):
        self.coverage_codes = set(_codes)
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
    assert first["snapshot_count"] == second["snapshot_count"] == 42
    assert len(repository.saved) == 42
    assert {"159941.SZ", "513650.SH"} <= {code for _, code in repository.saved}
    for code in ("159941.SZ", "513650.SH"):
        snapshot = repository.saved[(TRADE_DATE.isoformat(), code)]
        assert snapshot["ret_60d"] > 0
        assert snapshot["rank_5d"] > 0
        assert 0 <= snapshot["momentum_score"] <= 100
        assert 0 <= snapshot["entry_score"] <= 100
        assert 0.03 <= snapshot["stop_loss_pct"] <= 0.08
    assert first["candidate_count"] == 5
    assert all("score_components" in snapshot for snapshot in repository.saved.values())
    assert all(snapshot["reference_price"] > 0 for snapshot in repository.saved.values())
    assert all(0.03 <= snapshot["stop_loss_pct"] <= 0.08 for snapshot in repository.saved.values())
    assert all(
        snapshot["suggested_stop_price"]
        == pytest.approx(snapshot["reference_price"] * (1 - snapshot["stop_loss_pct"]))
        for snapshot in repository.saved.values()
    )


def test_cn_and_us_services_use_identical_stop_loss_calculation() -> None:
    cn_repository = FakeRepository(market="CN")
    us_repository = FakeRepository(market="US")
    ETFRotationService("CN", repository=cn_repository).run(TRADE_DATE)
    ETFRotationService("US", repository=us_repository).run(TRADE_DATE)
    cn_first = cn_repository.saved[sorted(cn_repository.saved)[0]]
    us_first = us_repository.saved[sorted(us_repository.saved)[0]]
    assert cn_first["reference_price"] == us_first["reference_price"]
    assert cn_first["realized_vol_20d"] == us_first["realized_vol_20d"]
    assert cn_first["stop_loss_pct"] == us_first["stop_loss_pct"]
    assert cn_first["suggested_stop_price"] == us_first["suggested_stop_price"]


def test_service_and_repository_reject_unsupported_markets_early() -> None:
    with pytest.raises(ValueError, match="expected CN or US"):
        ETFRotationService("HK")
    with pytest.raises(ValueError, match="expected CN or US"):
        ETFRotationRepository("HK", MagicMock())


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


def test_us_service_uses_us_calendar_and_shared_engine_functions() -> None:
    repository = FakeRepository(market="US")
    now = datetime(2026, 8, 26, 23, 0, tzinfo=timezone.utc)
    with (
        patch(
            "finance_analysis.etf_rotation.service.get_completed_trading_days", return_value=[TRADE_DATE]
        ) as calendar,
        patch(
            "finance_analysis.etf_rotation.service.calculate_features",
            wraps=__import__(
                "finance_analysis.etf_rotation.service", fromlist=["calculate_features"]
            ).calculate_features,
        ) as features,
        patch(
            "finance_analysis.etf_rotation.service.rank_cross_section",
            wraps=__import__(
                "finance_analysis.etf_rotation.service", fromlist=["rank_cross_section"]
            ).rank_cross_section,
        ) as ranking,
        patch(
            "finance_analysis.etf_rotation.service.calculate_momentum_score",
            wraps=__import__(
                "finance_analysis.etf_rotation.service", fromlist=["calculate_momentum_score"]
            ).calculate_momentum_score,
        ) as scoring,
        patch(
            "finance_analysis.etf_rotation.service.classify_state",
            wraps=__import__("finance_analysis.etf_rotation.service", fromlist=["classify_state"]).classify_state,
        ) as classifier,
        patch(
            "finance_analysis.etf_rotation.service.select_candidates",
            wraps=__import__("finance_analysis.etf_rotation.service", fromlist=["select_candidates"]).select_candidates,
        ) as selector,
    ):
        result = ETFRotationService("US", repository=repository, now=now).run()

    calendar.assert_called_once_with("us", 1, now)
    assert result["market"] == "US"
    assert result["universe_size"] == result["snapshot_count"] == 49
    assert features.call_count == 49
    ranking.assert_called_once()
    assert scoring.call_count == classifier.call_count == 49
    selector.assert_called_once()
    assert repository.coverage_codes == {member.code for member in enabled_etfs("US")}
    assert all(code.endswith(".US") for code in repository.coverage_codes)


def test_cn_service_coverage_scope_excludes_us_etfs() -> None:
    repository = FakeRepository(market="CN")
    ETFRotationService(repository=repository).run(TRADE_DATE)
    assert repository.coverage_codes == {member.code for member in enabled_etfs("CN")}
    assert not any(code.endswith(".US") for code in repository.coverage_codes)


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
    assert ETFRotationRepository(FakeDatabase()).upsert_snapshots(snapshots) == 42
    upsert_sql = str(session.execute.call_args_list[1].args[0].compile(dialect=postgresql.dialect()))
    upsert_params = session.execute.call_args_list[1].args[0].compile(dialect=postgresql.dialect()).params
    cleanup_sql = str(session.execute.call_args_list[2].args[0].compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT ON CONSTRAINT uix_etf_momentum_snapshot_date_symbol DO UPDATE" in upsert_sql
    assert {value for key, value in upsert_params.items() if key.startswith("market_")} == {"CN"}
    assert "DELETE FROM etf_momentum_snapshot" in cleanup_sql


def test_repository_lists_distinct_trade_dates_newest_first() -> None:
    session = MagicMock()
    session.execute.return_value.scalars.return_value = [date(2026, 8, 25), date(2026, 8, 24)]

    class FakeDatabase:
        @contextmanager
        def get_session(self):
            yield session

    assert ETFRotationRepository(FakeDatabase()).available_trade_dates() == [
        date(2026, 8, 25),
        date(2026, 8, 24),
    ]
    compiled = str(session.execute.call_args.args[0].compile())
    assert "DISTINCT" in compiled
    assert "etf_momentum_snapshot.market" in compiled
    assert "etf_momentum_snapshot.trade_date" in compiled
    assert "ORDER BY etf_momentum_snapshot.trade_date DESC" in compiled


def test_us_repository_forces_snapshot_market_instead_of_trusting_rows() -> None:
    session = MagicMock()
    session.execute.side_effect = [
        SimpleNamespace(all=lambda: [(member.code, index + 1) for index, member in enumerate(enabled_etfs("US"))]),
        MagicMock(),
        MagicMock(),
    ]

    class FakeDatabase:
        @contextmanager
        def session_scope(self):
            yield session

    fake = FakeRepository(market="US")
    ETFRotationService("US", repository=fake).run(TRADE_DATE)
    snapshots = list(fake.saved.values())
    snapshots[0]["market"] = "CN"
    assert ETFRotationRepository("US", FakeDatabase()).upsert_snapshots(snapshots) == 49
    params = session.execute.call_args_list[1].args[0].compile(dialect=postgresql.dialect()).params
    assert {value for key, value in params.items() if key.startswith("market_")} == {"US"}

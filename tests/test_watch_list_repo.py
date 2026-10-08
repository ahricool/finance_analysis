# -*- coding: utf-8 -*-
"""Tests for watch list repository field handling."""

from finance_analysis.database.models import WatchListItem
from finance_analysis.database.repositories.watch_list import WatchListRepo


class _FakeSession:
    def __init__(self, item=None):
        self.item = item

    def add(self, item):
        self.item = item

    def flush(self):
        pass

    def refresh(self, item):
        pass

    def expunge(self, item):
        pass

    def get(self, model, item_id):
        return self.item


class _FakeDB:
    def __init__(self, item=None):
        self.session = _FakeSession(item)

    def _run_write_transaction(self, operation_name, write_operation):
        return write_operation(self.session)


def _unique_constraint_columns(model) -> set[tuple[str, ...]]:
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in model.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }


def test_watch_list_create_accepts_market_type_and_favorite_flag():
    repo = WatchListRepo(db=_FakeDB())

    item = repo.create(
        uid=1,
        code=" aapl ",
        name=" Apple ",
        notes=" important ",
        market_type="US",
        is_favorite=True,
    )

    assert item.code == "AAPL"
    assert item.name == "Apple"
    assert item.notes == "important"
    assert item.market_type == "US"
    assert item.is_favorite is True


def test_watch_list_update_accepts_market_type_and_favorite_flag():
    repo = WatchListRepo(db=_FakeDB())
    item = repo.create(uid=1, code="600519", market_type="CN", is_favorite=True)

    updated = WatchListRepo(db=_FakeDB(item)).update(
        item.id or 1,
        uid=1,
        market_type="HK",
        is_favorite=False,
    )

    assert updated is item
    assert updated.market_type == "HK"
    assert updated.is_favorite is False


def test_watch_list_unique_identity_includes_market_type():
    assert ("uid", "market_type", "code") in _unique_constraint_columns(WatchListItem)


def test_watch_codes_use_explicit_market_and_preserve_storage_identity():
    from types import SimpleNamespace
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    engine = create_engine("sqlite://")
    WatchListItem.__table__.create(engine)
    db = SimpleNamespace(get_session=lambda: Session(engine))
    repo = WatchListRepo(db=db)
    with db.get_session() as session:
        session.add_all([
            WatchListItem(uid=1, code="AAPL", market_type="US"),
            WatchListItem(uid=1, code="BRK.B", market_type="US"),
            WatchListItem(uid=1, code="600519", market_type="CN"),
            WatchListItem(uid=1, code="00700", market_type="HK"),
            WatchListItem(uid=2, code="AAPL.US", market_type="US"),
        ])
        session.commit()
    assert set(repo.get_codes(uid=1)) == {"AAPL.US", "BRK.B.US", "600519.SH", "700.HK"}
    assert set(repo.get_codes(uid=1, market_type="US")) == {"AAPL.US", "BRK.B.US"}
    assert repo.get_codes(uid=2) == ["AAPL.US"]
    assert repo.get_by_code("AAPL", uid=1, market_type="US").code == "AAPL"
    engine.dispose()


def test_create_and_update_reject_region_conflicts_before_mutating_rows():
    import pytest

    db = _FakeDB()
    with pytest.raises(ValueError):
        WatchListRepo(db=db).create(uid=1, code="AAPL.US", market_type="CN")
    assert db.session.item is None
    item = WatchListItem(id=1, uid=1, code="AAPL.US", market_type="US", name="original")
    with pytest.raises(ValueError):
        WatchListRepo(db=_FakeDB(item)).update(1, uid=1, market_type="CN", name="changed")
    assert item.market_type == "US" and item.name == "original"


def test_legacy_invalid_codes_are_isolated_per_row_and_keep_uid_market_scopes(caplog):
    from types import SimpleNamespace
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    engine = create_engine("sqlite://")
    WatchListItem.__table__.create(engine)
    db = SimpleNamespace(get_session=lambda: Session(engine))
    with db.get_session() as session:
        session.add_all([
            WatchListItem(id=1, uid=1, code="AAPL.US", market_type="CN"),
            WatchListItem(id=2, uid=1, code="600519.SH", market_type="US"),
            WatchListItem(id=3, uid=1, code="MSFT", market_type="US"),
            WatchListItem(id=4, uid=2, code="600519", market_type="CN"),
        ])
        session.commit()
    repo = WatchListRepo(db=db)
    batch = repo.get_codes()
    assert set(batch) == {"MSFT.US", "600519.SH"}
    assert {item["watch_list_id"] for item in batch.validation_failures} == {1, 2}
    assert all(item["error"] for item in batch.validation_failures)
    assert "item_id=1" in caplog.text
    own = repo.get_codes(uid=2)
    assert own == ["600519.SH"] and own.validation_failures == []
    us = repo.get_codes(uid=1, market_type="US")
    assert us == ["MSFT.US"] and [item["watch_list_id"] for item in us.validation_failures] == [2]
    engine.dispose()

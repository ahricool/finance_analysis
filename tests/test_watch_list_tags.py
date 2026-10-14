"""Watch-list tags: persisted associations, filtering, transactions and ownership."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from finance_analysis.database.models import WatchListItem, WatchListTag
from finance_analysis.database.models.stock import Instrument
from finance_analysis.database.models.watch_list import watch_list_tag_link
from finance_analysis.database.repositories.watch_list import WatchListRepo
from finance_analysis.database.session import DatabaseManager
from finance_analysis.interfaces.api.v1.endpoints import watch_list


@pytest.fixture
def repo():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    for table in (WatchListItem.__table__, WatchListTag.__table__, watch_list_tag_link, Instrument.__table__):
        table.create(engine)

    class DB:
        def get_session(self):
            return Session(engine)

        _run_write_transaction = DatabaseManager._run_write_transaction

    repository = WatchListRepo(db=DB())
    yield repository
    engine.dispose()


def tag_ids(item):
    return {tag.id for tag in item.tags}


def test_multiple_tags_round_trip_and_partial_updates(repo):
    first = repo.create_tag(uid=1, name=" Growth ")
    item = repo.create(uid=1, code="AAPL", market_type="US", tags=[{"id": first.id}, {"name": "科技"}])
    assert {tag.name for tag in item.tags} == {"Growth", "科技"}
    assert tag_ids(repo.list_all(uid=1)[0]) == tag_ids(item)
    assert tag_ids(repo.get_by_id(item.id, uid=1)) == tag_ids(item)
    assert tag_ids(repo.update(item.id, uid=1, notes="备注", is_favorite=True)) == tag_ids(item)
    assert repo.update(item.id, uid=1, tags=[]).tags == []
    assert len(repo.list_tags(uid=1)) == 2  # Removing membership preserves labels.
    repo.delete(item.id, uid=1)
    assert len(repo.list_tags(uid=1)) == 2


def test_market_and_group_filters_and_totals(repo):
    tag = repo.create_tag(uid=1, name="共同")
    unused = repo.create_tag(uid=1, name="空分组")
    us = repo.create(uid=1, code="AAPL", market_type="US", tags=[{"id": tag.id}])
    cn = repo.create(uid=1, code="600519", market_type="CN", tags=[{"id": tag.id}])
    plain = repo.create(uid=1, code="MSFT", market_type="US")
    hk = repo.create(uid=1, code="00700", market_type="HK")
    repo.create(uid=2, code="AAPL", market_type="US", tags=[{"name": "共同"}])
    assert {i.id for i in repo.list_all(uid=1)} == {us.id, cn.id, plain.id, hk.id}
    assert [i.id for i in repo.list_all(uid=1, market_type="US", tag_id=tag.id)] == [us.id]
    assert [i.id for i in repo.list_all(uid=1, market_type="CN", tag_id=tag.id)] == [cn.id]
    assert [i.id for i in repo.list_all(uid=1, market_type="US", ungrouped=True)] == [plain.id]
    assert repo.list_all(uid=1, market_type="CN", ungrouped=True) == []
    assert repo.list_all(uid=1, tag_id=unused.id) == []
    assert repo.count(uid=1, market_type="US") == 2
    assert {t.id for t in repo.list_tags(uid=1)} == {tag.id, unused.id}


def test_rename_global_delete_and_user_isolation(repo):
    tag = repo.create_tag(uid=1, name="Tech")
    a = repo.create(uid=1, code="AAPL", market_type="US", tags=[{"id": tag.id}])
    b = repo.create(uid=1, code="600519", market_type="CN", tags=[{"id": tag.id}])
    other = repo.create_tag(uid=2, name="Tech")
    assert repo.rename_tag(tag.id, uid=2, name="盗用") is None
    assert not repo.delete_tag(tag.id, uid=2)
    assert repo.update(a.id, uid=2, tags=[]) is None
    with pytest.raises(ValueError, match="无权"):
        repo.update(a.id, uid=1, tags=[{"id": other.id}])
    assert repo.list_all(uid=2, tag_id=tag.id) == []
    repo.rename_tag(tag.id, uid=1, name=" 科技 ")
    assert all(item.tags[0].name == "科技" for item in repo.list_all(uid=1))
    repo.update(a.id, uid=1, tags=[])
    assert repo.get_by_id(b.id, uid=1).tags[0].name == "科技"
    repo.delete_tag(tag.id, uid=1)
    assert all(not item.tags for item in repo.list_all(uid=1))
    assert repo.count(uid=1) == 2
    assert repo.list_tags(uid=2)[0].id == other.id


def test_names_and_atomic_failures(repo):
    tag = repo.create_tag(uid=1, name=" Tech ")
    with pytest.raises(ValueError, match="同名"):
        repo.create_tag(uid=1, name="tECH")
    for invalid in (" ", "x" * 33):
        with pytest.raises(ValueError):
            repo.create_tag(uid=1, name=invalid)
    second = repo.create_tag(uid=1, name="Other")
    with pytest.raises(ValueError, match="同名"):
        repo.rename_tag(second.id, uid=1, name="TECH")
    item = repo.create(uid=1, code="AAPL", market_type="US", tags=[{"id": tag.id}])
    with pytest.raises(ValueError):
        repo.update(item.id, uid=1, notes="changed", tags=[{"name": "rollback"}, {"id": 99999}])
    assert repo.get_by_id(item.id, uid=1).notes is None
    assert tag_ids(repo.get_by_id(item.id, uid=1)) == {tag.id}
    with pytest.raises(IntegrityError):
        repo.create(uid=1, code="AAPL", market_type="US", tags=[{"name": "rollback"}])
    assert {t.name for t in repo.list_tags(uid=1)} == {"Tech", "Other"}
    # A newly typed spelling resolves the existing user's case-insensitive label.
    assert tag_ids(repo.update(item.id, uid=1, tags=[{"name": "tech"}])) == {tag.id}


def test_api_contracts_and_legacy_rows(repo, monkeypatch):
    monkeypatch.setattr(watch_list, "_repo", lambda: repo)
    uid = [1]
    monkeypatch.setattr(watch_list, "get_effective_uid", lambda _request: uid[0])
    app = FastAPI()
    app.include_router(watch_list.router, prefix="/watch-list")
    with TestClient(app) as client:
        old = repo.create(uid=1, code="00700", market_type="HK")
        assert client.get("/watch-list").json()["items"][0]["tags"] == []
        response = client.post("/watch-list", json={"code": "AAPL", "market_type": "US", "name": "Apple",
                                                    "tags": [{"name": "成长"}, {"name": "科技"}]})
        assert response.status_code == 201
        item = response.json()
        assert len(item["tags"]) == 2
        tag_id = item["tags"][0]["id"]
        assert len(client.put(f"/watch-list/{item['id']}", json={"is_favorite": True}).json()["tags"]) == 2
        assert len(client.put(f"/watch-list/{item['id']}", json={"notes": None}).json()["tags"]) == 2
        filtered = client.get(f"/watch-list?market=US&tag_id={tag_id}").json()
        assert len(filtered["items"]) == filtered["total"] == 1
        assert client.get("/watch-list?market=US&ungrouped=true").json() == {"items": [], "total": 1}
        assert client.get(f"/watch-list?ungrouped=true&tag_id={tag_id}").status_code == 422
        assert client.put(f"/watch-list/{item['id']}", json={"tags": None}).status_code == 422
        assert client.post("/watch-list/tags", json={"name": " "}).status_code == 422
        assert client.post("/watch-list/tags", json={"name": "x" * 33}).status_code == 422
        uid[0] = 2
        assert client.get("/watch-list/tags").json() == []
        assert client.put(f"/watch-list/tags/{tag_id}", json={"name": "other"}).status_code == 404
        assert client.delete(f"/watch-list/tags/{tag_id}").status_code == 404
        assert client.put(f"/watch-list/{item['id']}", json={"tags": []}).status_code == 404
        uid[0] = 1
        assert client.put(f"/watch-list/{item['id']}", json={"tags": []}).json()["tags"] == []
        assert len(client.get("/watch-list/tags").json()) == 2
        assert repo.get_by_id(old.id, uid=1).market_type == "HK"


def test_migration_preserves_existing_stocks_and_matches_models():
    path = Path(__file__).parents[1] / "alembic/versions/0075_watch_list_tags.py"
    spec = importlib.util.spec_from_file_location("watch_tags_revision", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    assert migration.down_revision == "0074_industry_reference"
    engine = create_engine("sqlite://")
    WatchListItem.__table__.create(engine)
    with engine.begin() as connection:
        connection.execute(WatchListItem.__table__.insert().values(uid=1, code="00700", market_type="HK"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        for table in (WatchListTag.__table__, watch_list_tag_link):
            actual = inspect(connection)
            assert {c["name"] for c in actual.get_columns(table.name)} == set(table.columns.keys())
            assert {i["name"] for i in actual.get_indexes(table.name)} == {i.name for i in table.indexes}
            assert {tuple(c["column_names"]) for c in actual.get_unique_constraints(table.name)} == {
                tuple(col.name for col in c.columns)
                for c in table.constraints if c.__class__.__name__ == "UniqueConstraint"
            }
            assert {fk["options"].get("ondelete") for fk in actual.get_foreign_keys(table.name)} == {
                fk.ondelete for fk in table.foreign_key_constraints
            }
        assert connection.execute(select(WatchListItem.code)).scalar() == "00700"
        assert connection.execute(select(WatchListTag.id)).first() is None
        migration.downgrade()
        assert inspect(connection).get_table_names() == ["watch_list"]
        assert connection.execute(select(WatchListItem.code)).scalar() == "00700"
    engine.dispose()



@pytest.mark.asyncio
async def test_realtime_fetches_only_the_current_user_market_and_group(repo, monkeypatch):
    from finance_analysis.interfaces.api.v1.endpoints import market_data

    tag = repo.create_tag(uid=1, name="分组")
    other = repo.create_tag(uid=2, name="分组")
    repo.create(uid=1, code="AAPL.US", market_type="US", tags=[{"id": tag.id}])
    repo.create(uid=1, code="MSFT.US", market_type="US")
    repo.create(uid=1, code="600519.SH", market_type="CN", tags=[{"id": tag.id}])
    repo.create(uid=2, code="NVDA.US", market_type="US", tags=[{"id": other.id}])
    monkeypatch.setattr(market_data, "WatchListRepo", lambda: repo)
    requested = []
    provider_requested = []

    class State:
        async def get_quotes(self, symbols):
            requested.append(list(symbols))
            return {}

        get_trend_states = get_quotes
        get_pattern_states = get_quotes

    def market_quotes(stocks):
        provider_requested.append([stock.symbol for stock in stocks])
        return {}

    monkeypatch.setattr(market_data, "_market_quotes", market_quotes)
    payload = await market_data._live_snapshot(1, State(), "watch-list", "US", tag.id, False)
    assert [quote["symbol"] for quote in payload["quotes"]] == ["AAPL.US"]
    assert all(symbols == ["AAPL.US"] for symbols in requested + provider_requested)
    requested.clear()
    payload = await market_data._live_snapshot(1, State(), "watch-list", "US", None, True)
    assert [quote["symbol"] for quote in payload["quotes"]] == ["MSFT.US"]
    payload = await market_data._live_snapshot(1, State(), "watch-list", "US", other.id, False)
    assert payload["quotes"] == []


def test_search_market_is_forwarded_to_existing_repository(monkeypatch):
    from types import SimpleNamespace
    from finance_analysis.interfaces.api.v1.endpoints import stocks
    calls = []

    def search(q, **kwargs):
        calls.append((q, kwargs))
        return []

    monkeypatch.setattr(stocks, "InstrumentRepository", lambda: SimpleNamespace(search_instruments=search))
    app = FastAPI()
    app.include_router(stocks.router, prefix="/stocks")
    with TestClient(app) as client:
        assert client.get("/stocks/search?q=Apple&market=US").status_code == 200
        assert calls[-1] == ("Apple", {"limit": 10, "markets": ["US"]})
        assert client.get("/stocks/search?q=茅台&market=CN").status_code == 200
        assert calls[-1][1]["markets"] == ["CN"]
        assert client.get("/stocks/search?q=Apple").status_code == 200
        assert calls[-1][1] == {"limit": 10}
        assert client.get("/stocks/search?q=Apple&market=INVALID").status_code == 422

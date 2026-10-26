"""Raw-board integrity is distinct from the explicit persisted-instrument scope."""

from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from finance_analysis.integrations.market_data.dragon_tiger import normalize_source
from finance_analysis.integrations.market_data.providers.fuyao import FuyaoProvider
from finance_analysis.dragon_tiger_flow.calculator import calculate
from tests.dragon_tiger_flow.test_flow import row, source, DAY, db  # noqa: F401


def raw_board(board):
    records = [
        row("600001.SH", ticker="600001"),
        row(None, ticker="300001", name="空代码股票", net_value="bad"),
        row("", ticker="300002", name="另一空代码股票"),
        row("600002.SH", ticker="600002", name="不在主数据", net_value="bad"),
        row("113001.SH", ticker="113001", name="示例转债"),
        row("123001.SZ", ticker="123001", name="示例转02"),
    ]
    data = source(records, board, groups=[{"name": "席位A", "rows": records}] if board == "hot_money" else [])
    data["stock_count"] = len({r["ticker"] for r in records})
    return data


@pytest.mark.parametrize("board", ["all", "org", "hot_money"])
def test_missing_unknown_and_bonds_are_discarded_before_business_validation(board):
    data = raw_board(board)
    # Even a bad master-data row for a bond must not bring it into equity totals.
    result = normalize_source(data, DAY, board, allowed_symbols={"600001.SH", "113001.SH", "123001.SZ"})
    rows = result["details"] if board == "hot_money" else result["rows"]
    assert [r["symbol"] for r in rows] == ["600001.SH"]
    assert result["upstream_count"] == 6 and result["upstream_stock_count"] == 6
    assert result["quality"]["discarded_counts"] == {"missing_thscode": 2, "bond": 2, "not_in_instrument": 1}
    assert result["quality"]["input_row_count"] == 6
    assert result["quality"]["retained_row_count"] == 1


@pytest.mark.parametrize("board", ["all", "org"])
def test_raw_count_mismatch_still_fails_before_discarding(board):
    data = raw_board(board)
    for field in ("count", "stock_count"):
        bad = dict(data, **{field: data[field] + 1})
        with pytest.raises(ValueError, match="Incomplete"):
            normalize_source(bad, DAY, board, allowed_symbols={"600001.SH"})


def test_no_ticker_or_thscode_is_discarded_without_inventing_identity():
    data = source([row(None), row("600001.SH")])
    result = normalize_source(data, DAY, "all", allowed_symbols={"600001.SH"})
    assert [r["symbol"] for r in result["rows"]] == ["600001.SH"]
    assert result["quality"]["discarded_counts"]["missing_thscode"] == 1


def test_empty_master_scope_produces_valid_empty_observation():
    normalized = {b: normalize_source(raw_board(b), DAY, b, allowed_symbols=set()) for b in ("all", "org", "hot_money")}
    result = calculate(
        {DAY: {"sources": normalized, "batch_id": "test", "generated_at": "2026-09-21T12:00:00Z"}}, [DAY]
    )
    assert result["complete"]
    assert result["summary"]["net_value"] == 0
    assert result["summary"]["stock_count"] == 0
    assert result["hot_money_details"] == []


def test_provider_uses_one_batch_lookup_and_no_remote_symbol_resolution():
    repository = Mock()
    # Membership means present, not necessarily ACTIVE. Retain a present delisted security.
    repository.get_by_codes.return_value = {"600001.SH": SimpleNamespace(listing_status="DELISTED")}
    provider = FuyaoProvider(
        api_key="test",
        instrument_repository=repository,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"code": 0, "data": raw_board("all")})),
    )
    result = provider.get_dragon_tiger_board(DAY)
    repository.get_by_codes.assert_called_once_with({"600001.SH", "600002.SH"})
    assert [r["symbol"] for r in result["rows"]] == ["600001.SH"]
    repository.get_by_code.assert_not_called()


def test_lookup_failure_is_not_converted_to_empty_success():
    repository = Mock()
    repository.get_by_codes.side_effect = RuntimeError("database unavailable")
    provider = FuyaoProvider(
        api_key="test",
        instrument_repository=repository,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"code": 0, "data": raw_board("all")})),
    )
    with pytest.raises(RuntimeError, match="database unavailable"):
        provider.get_dragon_tiger_board(DAY)


def test_filter_also_applies_to_extended_period_audit_rows():
    data = source([row("600001.SH", period=10), row("600002.SH", period=30)])
    result = normalize_source(data, DAY, "all", allowed_symbols={"600001.SH"})
    assert result["rows"] == []
    assert [r["symbol"] for r in result["excluded_rows"]] == ["600001.SH"]
    assert result["quality"]["discarded_counts"]["not_in_instrument"] == 1


def test_retained_records_still_reject_invalid_amounts_and_conflicts():
    for records in ([row(net_value="NaN")], [row(), row(value="999")]):
        with pytest.raises(ValueError):
            normalize_source(source(records), DAY, "all", allowed_symbols={"600001.SH"})


def test_repository_membership_and_published_quality(db, monkeypatch):
    from finance_analysis.database.models.stock import Instrument
    from finance_analysis.database.models.dragon_tiger_flow import DragonTigerFlowBatch as Batch
    from finance_analysis.database.repositories.stock import InstrumentRepository
    from finance_analysis.database.repositories.dragon_tiger_flow import DragonTigerFlowRepository
    from finance_analysis.dragon_tiger_flow.service import DragonTigerFlowService
    from finance_analysis.dragon_tiger_flow.config import VERSION

    with db.get_session() as session:
        Instrument.__table__.create(session.get_bind())
    with db.session_scope() as session:
        session.add(
            Instrument(
                code="600001.SH",
                native_code="600001",
                market="CN",
                name="测试",
                instrument_type="STOCK",
                currency="CNY",
                listing_status="DELISTED",
                source="TEST",
            )
        )
    provider = FuyaoProvider(
        api_key="test",
        instrument_repository=InstrumentRepository(db),
        transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json={"code": 0, "data": raw_board(request.url.params["board_type"])})
        ),
    )
    monkeypatch.setattr("finance_analysis.dragon_tiger_flow.service.validate_day", lambda _: None)
    repo = DragonTigerFlowRepository(db)
    assert DragonTigerFlowService(repo, provider).run(DAY)["status"] == "completed"
    with db.get_session() as session:
        batch = session.get(Batch, DAY)
        assert batch.rule_version == VERSION
        for board, data in batch.payload["sources"].items():
            assert data["quality"]["instrument_scope"] == "current_instrument"
            assert data["quality"]["retained_row_count"] == 1
    assert repo.has_complete(DAY)
    with db.session_scope() as session:
        session.get(Batch, DAY).rule_version = "dragon-tiger-flow-v1"
    assert not repo.has_complete(DAY)  # Default missing-only backfill must rebuild old scope.


def test_conflicting_retained_ticker_and_thscode_fail():
    with pytest.raises(ValueError, match="mismatch"):
        normalize_source(source([row("600001.SH", ticker="600002")]), DAY, "all", allowed_symbols={"600001.SH"})

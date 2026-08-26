from unittest.mock import MagicMock

from finance_analysis.database.models.stock import validate_market_data_code
from finance_analysis.etf_rotation.universe import ETF_UNIVERSE, US_ETF_UNIVERSE, enabled_etfs, universe_by_code
from finance_analysis.quant.markets import get_quant_universe_codes
from finance_analysis.stocks.market_scope import MarketDataScopeResolver
from finance_analysis.tasks.celery.jobs.market_data_sync.service import MarketDataSyncService


def test_static_cn_universe_has_42_unique_complete_members() -> None:
    assert len(ETF_UNIVERSE) == len(enabled_etfs("CN")) == 42
    assert len({member.code for member in ETF_UNIVERSE}) == 42
    assert all(member.category and member.theme and member.risk_group for member in enabled_etfs())


def test_cn_cross_border_etfs_have_canonical_codes_and_distinct_metadata() -> None:
    by_code = universe_by_code("CN")
    nasdaq = by_code["159941.SZ"]
    sp500 = by_code["513650.SH"]
    assert validate_market_data_code("CN", nasdaq.code) == "159941.SZ"
    assert validate_market_data_code("CN", sp500.code) == "513650.SH"
    assert (nasdaq.name, nasdaq.category, nasdaq.theme, nasdaq.risk_group) == (
        "广发纳指100ETF",
        "OVERSEAS_INDEX",
        "NASDAQ100",
        "US_GROWTH",
    )
    assert (sp500.name, sp500.category, sp500.theme, sp500.risk_group) == (
        "南方标普500ETF",
        "OVERSEAS_INDEX",
        "SP500",
        "US_LARGE_CAP",
    )
    assert nasdaq.market == sp500.market == "CN"
    assert nasdaq.asset_region == sp500.asset_region == "US"
    assert nasdaq.cross_border is sp500.cross_border is True
    assert {nasdaq.code, sp500.code}.isdisjoint({member.code for member in US_ETF_UNIVERSE})
    assert all(
        member.asset_region == "CN" and member.cross_border is False
        for member in ETF_UNIVERSE
        if member.code not in {nasdaq.code, sp500.code}
    )


def test_cn_scope_contains_enabled_strategy_dependencies_without_polluting_quant() -> None:
    watchlist = MagicMock()
    watchlist.list_all.return_value = []
    resolver = MarketDataScopeResolver(watchlist)
    scope = resolver.resolve("CN")
    enabled_codes = {member.code for member in enabled_etfs()}
    assert scope.strategy_dependency_codes == enabled_codes
    assert enabled_codes <= scope.synchronization_codes
    before = get_quant_universe_codes("CN")
    assert before == get_quant_universe_codes("CN")
    assert "588000.SH" not in before
    us_enabled_codes = {member.code for member in enabled_etfs("US")}
    assert resolver.resolve("US").strategy_dependency_codes == us_enabled_codes
    assert us_enabled_codes <= resolver.resolve("US").synchronization_codes


def test_us_universe_has_49_canonical_unique_members_and_required_broad_etfs() -> None:
    cn_codes = {member.code for member in enabled_etfs("CN")}
    us_codes = {member.code for member in enabled_etfs("US")}
    assert len(ETF_UNIVERSE) == 42
    assert len(US_ETF_UNIVERSE) == len(us_codes) == 49
    assert {"SPY.US", "QQQ.US", "IWM.US"} <= us_codes
    assert all(code.endswith(".US") for code in us_codes)
    assert cn_codes.isdisjoint(us_codes)
    by_code = {member.code: member for member in US_ETF_UNIVERSE}
    assert by_code["SPY.US"].risk_group == by_code["QQQ.US"].risk_group == "BROAD_LARGE_CAP"
    assert by_code["IWM.US"].risk_group == "BROAD_SMALL_CAP"


def test_us_strategy_dependency_records_enable_daily_sync_and_benchmarks_dedupe() -> None:
    records = MarketDataScopeResolver.strategy_dependency_records("US")
    assert len(records) == 49
    assert all(record["market"] == "US" and record["sync_daily"] is True for record in records)
    resolver = MarketDataScopeResolver(MagicMock(list_all=MagicMock(return_value=[])))
    scope = resolver.resolve("US")
    assert "SPY.US" in scope.benchmark_dependency_codes
    assert "SPY.US" in scope.strategy_dependency_codes
    assert len(scope.synchronization_codes) == len(
        scope.universe_codes | scope.benchmark_dependency_codes | scope.strategy_dependency_codes
    )


def test_cn_cross_border_etfs_are_daily_strategy_dependencies_without_watchlist() -> None:
    codes = {"159941.SZ", "513650.SH"}
    records = {
        record["code"]: record for record in MarketDataScopeResolver.strategy_dependency_records("CN")
    }
    assert len(records) == 42
    assert codes <= MarketDataScopeResolver.strategy_dependency_codes("CN")
    assert codes <= set(records)
    assert all(
        records[code]["market"] == "CN"
        and records[code]["sync_daily"] is True
        and records[code]["sync_minute"] is False
        for code in codes
    )
    resolver = MarketDataScopeResolver(MagicMock(list_all=MagicMock(return_value=[])))
    assert codes <= resolver.resolve("CN").synchronization_codes


def test_disabled_member_is_excluded_from_strategy_dependencies(monkeypatch) -> None:
    from finance_analysis.etf_rotation import universe

    disabled = universe.ETFUniverseMember("588000.SH", "科创50ETF", "BROAD_INDEX", "STAR50", "BROAD_GROWTH", False)
    monkeypatch.setattr(universe, "ETF_UNIVERSE", (disabled,))
    assert MarketDataScopeResolver.strategy_dependency_codes("CN") == set()
    assert MarketDataScopeResolver.strategy_dependency_records("CN") == []


def test_cn_sync_scope_registers_static_strategy_members_as_enabled() -> None:
    watchlist = MagicMock()
    watchlist.list_all.return_value = []
    symbol_repository = MagicMock()
    symbol_repository.list_enabled_daily_by_codes.return_value = []
    market_data = MagicMock()
    market_data.registry.names.return_value = []
    service = MarketDataSyncService(
        "CN",
        symbol_repository=symbol_repository,
        stock_repository=MagicMock(),
        adjustment_repository=MagicMock(),
        scope_resolver=MarketDataScopeResolver(watchlist),
        market_data_service=market_data,
    )
    service.load_scope()
    strategy_call = symbol_repository.upsert_symbols.call_args_list[0]
    assert len(strategy_call.args[0]) == 42
    assert strategy_call.kwargs["force_daily_sync"] is True
    strategy_records = {record["code"]: record for record in strategy_call.args[0]}
    assert {"159941.SZ", "513650.SH"} <= set(strategy_records)

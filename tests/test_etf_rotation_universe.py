from unittest.mock import MagicMock

from finance_analysis.etf_rotation.universe import ETF_UNIVERSE, US_ETF_UNIVERSE, enabled_etfs
from finance_analysis.quant.markets import get_quant_universe_codes
from finance_analysis.stocks.market_scope import MarketDataScopeResolver
from finance_analysis.tasks.celery.jobs.market_data_sync.service import MarketDataSyncService
from finance_analysis.trend_following.universe import get_universe


def test_static_universe_has_unique_complete_members() -> None:
    assert len(ETF_UNIVERSE) == 42
    assert len({member.code for member in ETF_UNIVERSE}) == len(ETF_UNIVERSE)
    assert all(member.category and member.theme and member.risk_group for member in enabled_etfs())


def test_cn_scope_contains_enabled_strategy_dependencies_without_polluting_quant() -> None:
    watchlist = MagicMock()
    watchlist.list_all.return_value = []
    resolver = MarketDataScopeResolver(watchlist)
    scope = resolver.resolve("CN")
    enabled_codes = {member.code for member in enabled_etfs()}
    trend_codes = {member.code for member in get_universe("CN")}
    assert scope.strategy_dependency_codes == enabled_codes | trend_codes
    assert enabled_codes <= scope.synchronization_codes
    before = get_quant_universe_codes("CN")
    assert before == get_quant_universe_codes("CN")
    assert "588000.SH" not in before
    us_enabled_codes = {member.code for member in enabled_etfs("US")}
    us_trend_codes = {member.code for member in get_universe("US")}
    assert resolver.resolve("US").strategy_dependency_codes == us_enabled_codes | us_trend_codes
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
    expected_codes = (
        {member.code for member in enabled_etfs("US")}
        | {member.code for member in get_universe("US")}
    )
    assert {record["code"] for record in records} == expected_codes
    assert all(record["market"] == "US" and record["sync_daily"] is True for record in records)
    resolver = MarketDataScopeResolver(MagicMock(list_all=MagicMock(return_value=[])))
    scope = resolver.resolve("US")
    assert "SPY.US" in scope.benchmark_dependency_codes
    assert "SPY.US" in scope.strategy_dependency_codes
    assert len(scope.synchronization_codes) == len(
        scope.universe_codes | scope.benchmark_dependency_codes | scope.strategy_dependency_codes
    )


def test_disabled_member_is_excluded_from_strategy_dependencies(monkeypatch) -> None:
    from finance_analysis.etf_rotation import universe

    disabled = universe.ETFUniverseMember("588000.SH", "科创50ETF", "BROAD_INDEX", "STAR50", "BROAD_GROWTH", False)
    monkeypatch.setattr(universe, "ETF_UNIVERSE", (disabled,))
    trend_codes = {member.code for member in get_universe("CN")}
    assert MarketDataScopeResolver.strategy_dependency_codes("CN") == trend_codes
    assert {item["code"] for item in MarketDataScopeResolver.strategy_dependency_records("CN")} == trend_codes


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
        scope_resolver=MarketDataScopeResolver(watchlist),
        market_data_service=market_data,
    )
    service.load_scope()
    strategy_call = symbol_repository.upsert_symbols.call_args_list[0]
    expected_codes = (
        {member.code for member in enabled_etfs("CN")}
        | {member.code for member in get_universe("CN")}
    )
    assert {item["code"] for item in strategy_call.args[0]} == expected_codes
    assert strategy_call.kwargs["force_daily_sync"] is True

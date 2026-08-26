from unittest.mock import MagicMock

from finance_analysis.etf_rotation.universe import ETF_UNIVERSE, enabled_etfs
from finance_analysis.quant.markets import get_quant_universe_codes
from finance_analysis.stocks.market_scope import MarketDataScopeResolver
from finance_analysis.tasks.celery.jobs.market_data_sync.service import MarketDataSyncService


def test_static_universe_has_40_unique_complete_members() -> None:
    assert len(ETF_UNIVERSE) == 40
    assert len({member.code for member in ETF_UNIVERSE}) == 40
    assert all(member.category and member.theme and member.risk_group for member in enabled_etfs())


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
    assert resolver.resolve("US").strategy_dependency_codes == frozenset()


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
    assert len(strategy_call.args[0]) == 40
    assert strategy_call.kwargs["force_daily_sync"] is True

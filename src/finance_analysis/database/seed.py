"""Explicit one-time/reference-data seed helpers."""

from __future__ import annotations

from finance_analysis.core.time import utc_now


def seed_quant_reference_data(db_manager=None) -> dict:
    """Idempotently seed model definitions and the two supported dynamic universes."""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from finance_analysis.database.models.quant import ModelDefinition, QuantUniverse
    from finance_analysis.database.session import DatabaseManager
    from finance_analysis.quant.markets import DEFAULT_QUANT_UNIVERSES

    manager = db_manager or DatabaseManager.get_instance()
    with manager.session_scope() as session:
        definitions = [
            ("market_regime_rules", "Market regime rules", "market_regime", "classification"),
            ("time_series_logistic", "Shared panel logistic baseline", "time_series", "classification"),
            ("time_series_lgbm", "Shared panel LightGBM", "time_series", "regression"),
            ("cross_section_ridge", "Cross-sectional Ridge baseline", "cross_section", "regression"),
            ("cross_section_lgbm", "Qlib Alpha158 LightGBM", "cross_section", "regression"),
            ("signal_fusion", "Versioned signal fusion", "fusion", "ranking"),
        ]
        for key, name, model_type, task_type in definitions:
            values = dict(
                key=key, name=name, model_type=model_type, task_type=task_type, frequency="day", enabled=True,
                target_definition={"entry": "T+1 open", "exit": "T+5 close", "unit": "percentage_points"},
                default_config={}, supported_markets=["US", "CN"],
            )
            session.execute(pg_insert(ModelDefinition).values(**values).on_conflict_do_update(
                index_elements=[ModelDefinition.key],
                set_={"supported_markets": values["supported_markets"], "updated_at": utc_now()},
            ))
        for values in (
            {
                "key": DEFAULT_QUANT_UNIVERSES["US"], "name": "S&P 500 + US watchlist", "market": "US",
                "description": "Dynamic mirror of the shared US daily synchronization scope.",
                "enabled": True, "is_dynamic": True, "benchmark_code": "QQQ.US",
                "sector_benchmark_mode": "member_or_synthetic", "config": {"scope_resolver": "MarketDataScopeResolver"},
            },
            {
                "key": DEFAULT_QUANT_UNIVERSES["CN"], "name": "沪深300 + A股自选", "market": "CN",
                "description": "Dynamic mirror of the shared CN daily synchronization scope.",
                "enabled": True, "is_dynamic": True, "benchmark_code": "510300.SH",
                "sector_benchmark_mode": "member_or_synthetic", "config": {"scope_resolver": "MarketDataScopeResolver"},
            },
        ):
            session.execute(pg_insert(QuantUniverse).values(**values).on_conflict_do_update(
                index_elements=[QuantUniverse.key],
                set_={key: value for key, value in values.items() if key != "key"},
            ))
    return {
        "universes": [DEFAULT_QUANT_UNIVERSES["US"], DEFAULT_QUANT_UNIVERSES["CN"]],
        "model_definitions": [key for key, *_ in definitions],
    }


def seed_nasdaq100_market_data_symbols(db_manager=None) -> int:
    """Idempotently seed Nasdaq-100 symbols using canonical ``.US`` codes.

    Runtime synchronization never reads the Python constituent constant; only
    this initialization boundary does.
    """
    from finance_analysis.database.repositories.stock import MarketDataSymbolRepository
    from finance_analysis.stocks.reference_data.stock_index import NASDAQ100_STOCK_INDEX

    return MarketDataSymbolRepository(db_manager).upsert_symbols(
        {
            "market": "US",
            "code": f"{ticker}.US",
            "name": name,
            "enabled": True,
            "sync_daily": True,
            "sync_minute": True,
        }
        for ticker, name in NASDAQ100_STOCK_INDEX.items()
    )


def seed_market_data_reference_symbols(db_manager=None) -> dict[str, int]:
    """Idempotently seed the S&P 500 and CSI 300 daily synchronization universes."""
    from finance_analysis.database.repositories.stock import MarketDataSymbolRepository
    from finance_analysis.stocks.reference_data.stock_index import CSI300_STOCK_INDEX, SP500_STOCK_INDEX
    from finance_analysis.stocks.market_scope import MarketDataScopeResolver

    repository = MarketDataSymbolRepository(db_manager)
    us_count = repository.upsert_symbols(
        {
            "market": "US",
            "code": f"{ticker}.US",
            "name": name,
            "enabled": True,
            "sync_daily": True,
            "sync_minute": False,
        }
        for ticker, name in SP500_STOCK_INDEX.items()
    )
    cn_count = repository.upsert_symbols(
        {
            "market": "CN",
            "code": code,
            "name": name,
            "enabled": True,
            "sync_daily": True,
            "sync_minute": False,
        }
        for code, name in CSI300_STOCK_INDEX.items()
    )
    repository.upsert_symbols(MarketDataScopeResolver.dependency_records("US"))
    repository.upsert_symbols(MarketDataScopeResolver.dependency_records("CN"))
    return {"US": us_count, "CN": cn_count}

"""Explicit one-time/reference-data seed helpers."""

from __future__ import annotations

from datetime import date

from finance_analysis.core.time import utc_now


def seed_quant_reference_data(db_manager=None) -> dict:
    """Seed the fixed observation universe and versioned model definitions.

    Only symbols already present in ``market_data_symbol`` are linked. Missing
    candidates are recorded in universe config and never invented.
    """
    from sqlalchemy import select
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from finance_analysis.database.models.quant import ModelDefinition, QuantUniverse, QuantUniverseMember
    from finance_analysis.database.models.stock import MarketDataSymbol
    from finance_analysis.database.session import DatabaseManager

    manager = db_manager or DatabaseManager.get_instance()
    candidates = ["NVDA", "AVGO", "AMD", "MU", "AMAT", "LRCX", "KLAC", "ASML", "TSM", "MRVL", "ARM", "QCOM", "INTC", "COHR", "ANET", "VRT"]
    sector = {ticker: "semiconductor" for ticker in candidates}
    sector["ANET"] = "networking"; sector["VRT"] = "infrastructure"; sector["COHR"] = "optical"
    with manager.session_scope() as session:
        symbols = {row.code: row for row in session.execute(select(MarketDataSymbol).where(
            MarketDataSymbol.code.in_([f"{ticker}.US" for ticker in candidates] + ["QQQ.US", "SPY.US", "SOXX.US"])
        )).scalars()}
        missing = [f"{ticker}.US" for ticker in candidates if f"{ticker}.US" not in symbols]
        benchmark = "SOXX.US" if "SOXX.US" in symbols else ("QQQ.US" if "QQQ.US" in symbols else None)
        universe_values = {
            "key": "us_ai_semiconductor", "name": "US AI & Semiconductor", "market": "US",
            "description": "Fixed observation universe; historical membership is not asserted.",
            "enabled": True, "is_dynamic": False, "benchmark_code": benchmark,
            "sector_benchmark_mode": "member",
            "config": {"fixed_observation_universe": True, "survivorship_bias_warning": True, "missing_symbols": missing,
                       "sector_benchmarks": {"semiconductor": "SOXX.US", "networking": "QQQ.US", "infrastructure": "QQQ.US", "optical": "QQQ.US"}},
        }
        universe = session.execute(pg_insert(QuantUniverse).values(**universe_values).on_conflict_do_update(
            index_elements=[QuantUniverse.key], set_={"benchmark_code": benchmark, "config": universe_values["config"]}
        ).returning(QuantUniverse)).scalar_one()
        today = date.today()
        for ticker in candidates:
            symbol = symbols.get(f"{ticker}.US")
            if not symbol: continue
            session.execute(pg_insert(QuantUniverseMember).values(
                universe_id=universe.id, symbol_id=symbol.id, effective_from=today,
                sector_key=sector[ticker], sector_benchmark_code="SOXX.US" if sector[ticker] == "semiconductor" else "QQQ.US",
                enabled=True,
            ).on_conflict_do_nothing(constraint="uix_quant_member_period"))
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
                "key": "us_sp500_watchlist", "name": "S&P 500 + US watchlist", "market": "US",
                "description": "Dynamic mirror of the shared US daily synchronization scope.",
                "enabled": True, "is_dynamic": True, "benchmark_code": "QQQ.US",
                "sector_benchmark_mode": "member_or_synthetic", "config": {"scope_resolver": "MarketDataScopeResolver"},
            },
            {
                "key": "cn_csi300_watchlist", "name": "沪深300 + A股自选", "market": "CN",
                "description": "Dynamic mirror of the shared CN daily synchronization scope.",
                "enabled": True, "is_dynamic": True, "benchmark_code": "510300.SH",
                "sector_benchmark_mode": "member_or_synthetic", "config": {"scope_resolver": "MarketDataScopeResolver"},
            },
        ):
            session.execute(pg_insert(QuantUniverse).values(**values).on_conflict_do_update(
                index_elements=[QuantUniverse.key],
                set_={key: value for key, value in values.items() if key != "key"},
            ))
    return {"universe": "us_ai_semiconductor", "matched": len(candidates) - len(missing), "missing": missing}


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
